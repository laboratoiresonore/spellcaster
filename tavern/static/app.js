/* ── Mobile sidebar toggle ── */
function toggleMobileSidebar() {
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    sidebar.classList.toggle('open');
    backdrop.classList.toggle('visible');
}
function closeMobileSidebar() {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-backdrop').classList.remove('visible');
}
// Close sidebar when a character is tapped on mobile
function onMobileCharacterSelect() {
    if (window.innerWidth <= 768) closeMobileSidebar();
}

const chatStream = document.getElementById('chat-stream');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const resetBtn = document.getElementById('reset-btn');
const characterList = document.getElementById('character-list');
const activeAvatar = document.getElementById('active-avatar');
const activeName = document.getElementById('active-character-name');
const activeSubtext = document.getElementById('active-character-subtext');
const overlay = document.getElementById('loading-overlay');
const searchInput = document.getElementById('character-search');

const renameBtn = document.getElementById('rename-btn');
const generateAvatarBtn = document.getElementById('generate-avatar-btn');
const generateBgBtn = document.getElementById('generate-bg-btn');
const batchGenerateBtn = document.getElementById('batch-generate-btn');
const llmDot = document.getElementById('llm-dot');
const llmStatus = document.getElementById('llm-status');
const comfyDot = document.getElementById('comfy-dot');
const comfyStatus = document.getElementById('comfy-status');
// SillyTavern + Signal Bridge no longer have standalone dot indicators
// — their liveness surfaces through the shared chip row. checkSillyTavern
// and checkSignalBridge still exist (they trigger the Guild's probe,
// which in turn posts a heartbeat into the interface registry) but they
// don't touch any DOM here.

// Settings
const settingsBtn = document.getElementById('settings-btn');
const settingsModal = document.getElementById('settings-modal');
const settingsCancel = document.getElementById('settings-cancel');
const settingsSave = document.getElementById('settings-save');
const koboldUrlInput = document.getElementById('kobold-url-input');
const comfyUrlInput = document.getElementById('comfy-url-input');
const stUrlInput = document.getElementById('st-url-input');
const bridgeUrlInput = document.getElementById('bridge-url-input');

// Rename Elements
const renameModal = document.getElementById('rename-modal');
const renameInput = document.getElementById('rename-input');
const renameCancel = document.getElementById('rename-cancel');
const renameSave = document.getElementById('rename-save');
const renameLlmBtn = document.getElementById('rename-llm-btn');

// Defaults — will be overridden by server config or localStorage
let koboldUrl = localStorage.getItem('kobold_url') || 'http://127.0.0.1:5001';
let comfyUrl = localStorage.getItem('comfy_url') || 'http://127.0.0.1:8188';
let stUrl = localStorage.getItem('sillytavern_url') || 'http://127.0.0.1:8000';
let bridgeUrl = localStorage.getItem('signal_bridge_url') || 'http://127.0.0.1:8765';
let llmMode = 'local';  // 'local' (Ollama/KoboldAI) or 'horde' (AI Horde)

// Probe a local LLM server for liveness. Works for Ollama (/api/tags)
// OR KoboldCpp (/api/v1/model). Returns true if either responds.
async function probeLlm(url) {
    for (const path of ['/api/tags', '/api/v1/model']) {
        try {
            const r = await fetch(`${url}${path}`, { signal: AbortSignal.timeout(5000) });
            if (r.ok) return true;
        } catch (e) { /* try next */ }
    }
    return false;
}

async function _guildLlmHealthy() {
    try {
        const r = await fetch('/api/llm_status', { cache: 'no-store', signal: AbortSignal.timeout(3000) });
        if (!r.ok) return true;
        const s = await r.json();
        if (s.state === 'error') return false;
        if (s.last_error && /exhausted/i.test(s.last_error)) return false;
        return true;
    } catch (e) {
        return true;
    }
}

let characters = [];
let activeCharacterId = null;
let systemPrompt = "";
let chatHistory = [];

let _serverGeneratedAssets = {};
let _sidebarRevealed = false;

// ═══════════════════════════════════════════════════════════════════════
//  Privacy Banner — persistent warning when Horde mode is active
// ═══════════════════════════════════════════════════════════════════════
function _updatePrivacyBanner() {
    let banner = document.getElementById('horde-privacy-banner');
    if (llmMode === 'horde') {
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'horde-privacy-banner';
            banner.style.cssText = 'position:fixed;bottom:0;left:0;right:0;z-index:9998;' +
                'background:linear-gradient(90deg,#3d1010,#501515);color:#ff9999;' +
                'padding:6px 16px;text-align:center;font-size:12px;font-weight:600;' +
                'border-top:2px solid #ff4757;font-family:Outfit,sans-serif;';
            banner.innerHTML = '\u26a0 HORDE MODE — ZERO PRIVACY — All prompts visible to volunteer workers. ' +
                '<span style="color:#ff6b6b;cursor:pointer;text-decoration:underline;" ' +
                'onclick="document.getElementById(\'horde-privacy-banner\').remove()" ' +
                'title="Dismiss until next page load">dismiss</span>';
            document.body.appendChild(banner);
        }
    } else if (banner) {
        banner.remove();
    }
}  // cached for background URL fallback

// ═══════════════════════════════════════════════════════════════════════
//  LLM Generate — routes to KoboldAI (local) or AI Horde (server proxy)
// ═══════════════════════════════════════════════════════════════════════
async function llmGenerate(params) {
    if (llmMode === 'horde') {
        // Route through server-side Horde proxy (avoids CORS)
        const res = await fetch('/api/horde_generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params)
        });
        return await res.json();
    } else {
        // Route through Guild server proxy — handles ComfyUI-native LLM,
        // KoboldCpp, and Ollama fallback automatically. The browser can't
        // call ComfyUI's workflow API directly for text generation.
        const res = await fetch('/api/llm_generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params)
        });
        if (!res.ok) throw new Error(`LLM proxy returned ${res.status}`);
        return await res.json();
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  Magical Particle System (pure JS canvas, zero dependencies)
// ═══════════════════════════════════════════════════════════════════════
(function initParticles() {
    const canvas = document.getElementById('magic-particles');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let particles = [];
    const MAX = 50;

    function resize() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }
    window.addEventListener('resize', resize);
    resize();

    class Particle {
        constructor() { this.reset(); }
        reset() {
            this.x = Math.random() * canvas.width;
            this.y = canvas.height + 10;
            this.size = Math.random() * 3 + 1;
            this.speedY = -(Math.random() * 0.6 + 0.15);
            this.speedX = (Math.random() - 0.5) * 0.3;
            this.opacity = Math.random() * 0.5 + 0.1;
            this.fadeRate = Math.random() * 0.002 + 0.001;
            this.hue = Math.random() > 0.5 ? 275 : (Math.random() > 0.5 ? 240 : 320);
            this.twinkle = Math.random() * Math.PI * 2;
        }
        update() {
            this.y += this.speedY;
            this.x += this.speedX + Math.sin(this.twinkle) * 0.15;
            this.twinkle += 0.02;
            this.opacity -= this.fadeRate;
            if (this.opacity <= 0 || this.y < -10) this.reset();
        }
        draw() {
            const flicker = 0.5 + 0.5 * Math.sin(this.twinkle * 3);
            ctx.globalAlpha = this.opacity * flicker;
            ctx.fillStyle = `hsl(${this.hue}, 80%, 75%)`;
            ctx.shadowBlur = this.size * 4;
            ctx.shadowColor = `hsl(${this.hue}, 80%, 65%)`;
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
            ctx.fill();
            ctx.shadowBlur = 0;
        }
    }

    for (let i = 0; i < MAX; i++) {
        const p = new Particle();
        p.y = Math.random() * canvas.height; // scatter initial positions
        particles.push(p);
    }

    function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        particles.forEach(p => { p.update(); p.draw(); });
        ctx.globalAlpha = 1;
        requestAnimationFrame(animate);
    }
    // Mouse-interactive arcane trail particles
    let _mouseParticles = [];
    window._spawnMouseParticle = function(mx, my) {
        if (_mouseParticles.length > 30) return;  // cap
        for (let i = 0; i < 3; i++) {
            const mp = {
                x: mx + (Math.random()-0.5)*10,
                y: my + (Math.random()-0.5)*10,
                size: Math.random() * 2.5 + 0.5,
                vx: (Math.random()-0.5) * 2,
                vy: (Math.random()-0.5) * 2 - 1,
                life: 1.0,
                hue: Math.random() > 0.5 ? 275 : 260
            };
            _mouseParticles.push(mp);
        }
    };

    function animateAll() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        // Background ambient particles
        particles.forEach(p => { p.update(); p.draw(); });
        // Mouse trail particles
        _mouseParticles = _mouseParticles.filter(mp => {
            mp.x += mp.vx;
            mp.y += mp.vy;
            mp.vy += 0.02; // gravity
            mp.life -= 0.025;
            if (mp.life <= 0) return false;
            ctx.globalAlpha = mp.life * 0.8;
            ctx.fillStyle = `hsl(${mp.hue}, 90%, 75%)`;
            ctx.shadowBlur = mp.size * 5;
            ctx.shadowColor = `hsl(${mp.hue}, 90%, 65%)`;
            ctx.beginPath();
            ctx.arc(mp.x, mp.y, mp.size * mp.life, 0, Math.PI * 2);
            ctx.fill();
            ctx.shadowBlur = 0;
            return true;
        });
        ctx.globalAlpha = 1;
        requestAnimationFrame(animateAll);
    }
    animateAll();
})();

// HTML-escape for anything that lands inside an innerHTML template
// literal. Chat messages, character-card fields (.name / .subtext /
// .personality), asset titles, and LLM output all flow through
// template strings that previously injected raw; this escapes the
// five chars HTML treats as special in element content or quoted
// attributes. Use `${_esc(x)}` in place of `${x}` at every sink.
function _esc(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Narrow URL validator for src= attributes derived from untrusted
// sources (avatar URLs, asset URLs from the Guild's event bus). Only
// http(s):, data:image/*, or relative /api/ paths pass. Returns a
// safe placeholder if the input is hostile.
function _safeSrc(u) {
    if (typeof u !== 'string' || !u) return '';
    if (u.startsWith('/') && !u.startsWith('//')) return u;
    try {
        const p = new URL(u, window.location.href);
        if (p.protocol === 'http:' || p.protocol === 'https:') return u;
        if (p.protocol === 'data:' && /^data:image\//i.test(u)) return u;
    } catch { /* fall through */ }
    return '';
}

// ComfyUI logo as inline SVG for system messages
const USER_SPARKLE_SVG = `<svg class="user-sparkle" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" fill="white">
  <path d="M16 2 L18 12 L28 14 L18 16 L16 26 L14 16 L4 14 L14 12 Z" opacity="0.9"/>
  <path d="M25 4 L25.8 7 L28.8 7.8 L25.8 8.6 L25 11.6 L24.2 8.6 L21.2 7.8 L24.2 7 Z" opacity="0.6"/>
  <path d="M7 22 L7.6 24 L9.6 24.6 L7.6 25.2 L7 27.2 L6.4 25.2 L4.4 24.6 L6.4 24 Z" opacity="0.5"/>
  <circle cx="24" cy="24" r="1" opacity="0.4"/>
  <circle cx="8" cy="6" r="0.8" opacity="0.35"/>
</svg>`;

const COMFYUI_LOGO_SVG = `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="cg" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#B246F2"/><stop offset="100%" stop-color="#6C63FF"/></linearGradient></defs>
  <circle cx="32" cy="32" r="28" fill="none" stroke="url(#cg)" stroke-width="3"/>
  <path d="M22 20 L42 32 L22 44 Z" fill="url(#cg)" opacity="0.9"/>
  <circle cx="32" cy="32" r="6" fill="none" stroke="url(#cg)" stroke-width="2" opacity="0.6"/>
</svg>`;

// Get current wizard avatar URL helper
function _getActiveWizardAvatarStyle() {
    const char = characters.find(c => c.id === activeCharacterId);
    if (!char) return '';
    const avatarUrl = char.avatar_url || `/api/avatar/${char.id}`;
    const gradient = `linear-gradient(135deg, ${char.color1 || '#B246F2'}, ${char.color2 || '#6C63FF'})`;
    return `background: ${gradient}; background-image: url('${avatarUrl}'); background-size: cover; background-position: center top;`;
}

async function syncServerAssets() {
    // Fetch any assets pre-generated by guild_launcher.py during setup
    // and ALWAYS overwrite local copies — the server is the source of
    // truth for generated assets. The previous "if (!char.avatar_url)"
    // guard caused a regression where stale localStorage values blocked
    // fresh server avatars from showing up even after a hard refresh.
    try {
        const res = await fetch('/api/generated_assets');
        const assets = await res.json();
        _serverGeneratedAssets = assets;  // cache for applyGlobalBackground fallback
        if (Object.keys(assets).length === 0) return;

        let savedIdentities = JSON.parse(localStorage.getItem('guild_identities') || '{}');
        let synced = 0;
        for (const [charId, assetUrls] of Object.entries(assets)) {
            const char = characters.find(c => c.id === charId);
            if (!char) continue;

            // Apply to character in memory — server data ALWAYS wins
            if (assetUrls.avatar_url) {
                char.avatar_url = assetUrls.avatar_url;
                synced++;
            }
            if (assetUrls.animated_url) {
                char.animated_url = assetUrls.animated_url;
                synced++;
            }

            // Persist to localStorage — overwrite any stale entries
            if (assetUrls.avatar_url || assetUrls.animated_url) {
                savedIdentities[charId] = savedIdentities[charId] || {};
                if (assetUrls.avatar_url)
                    savedIdentities[charId].avatar_url = assetUrls.avatar_url;
                if (assetUrls.animated_url)
                    savedIdentities[charId].animated_url = assetUrls.animated_url;
                savedIdentities[charId].name = savedIdentities[charId].name || char.name;
            }
        }

        if (synced > 0) {
            localStorage.setItem('guild_identities', JSON.stringify(savedIdentities));
            console.log(`[Guild] Synced ${synced} pre-generated assets from server`);
        }
    } catch(e) {
        console.log('[Guild] No pre-generated assets available');
    }
}

async function syncServerIdentities() {
    // Server-persisted wizard identity overrides (survive browser clears)
    try {
        const res = await fetch('/api/wizard_identities');
        const serverIds = await res.json();
        if (Object.keys(serverIds).length === 0) return;

        // Server OVERWRITES localStorage for all keys it has
        let local = JSON.parse(localStorage.getItem('guild_identities') || '{}');
        let synced = 0;
        for (const [charId, srvData] of Object.entries(serverIds)) {
            if (!local[charId]) local[charId] = {};
            for (const key of ['name', 'personality', 'avatar_url', 'animated_url']) {
                if (srvData[key]) {
                    local[charId][key] = srvData[key];
                    synced++;
                }
            }
        }
        if (synced > 0) {
            localStorage.setItem('guild_identities', JSON.stringify(local));
            console.log(`[Guild] Synced ${synced} identity field(s) from server`);
        }
    } catch(e) {
        console.log('[Guild] Could not sync wizard identities from server');
    }
}

async function syncServerLoraToggles() {
    // Server-persisted LoRA enabled/disabled state (survive browser clears)
    try {
        const res = await fetch('/api/lora_toggles');
        const serverToggles = await res.json();
        if (Object.keys(serverToggles).length === 0) return;

        // Merge: server fills any gaps, localStorage takes priority
        let local = JSON.parse(localStorage.getItem('lora_enabled') || '{}');
        let synced = 0;
        for (const [charId, srvState] of Object.entries(serverToggles)) {
            if (!local[charId]) {
                local[charId] = srvState;
                synced++;
            }
        }
        if (synced > 0) {
            localStorage.setItem('lora_enabled', JSON.stringify(local));
            loraEnabledState = local;
            console.log(`[Guild] Synced ${synced} LoRA toggle set(s) from server`);
        }
    } catch(e) {
        console.log('[Guild] Could not sync LoRA toggles from server');
    }
}

// Convert a number of bytes into a short GB string ("12.4").
function _fmtGB(bytes) {
    if (!bytes || bytes <= 0) return "0.0";
    return (bytes / (1024 ** 3)).toFixed(1);
}

// Build one meter HTML block: "label used/total GB [=====]"
function _buildMeter(label, used, total) {
    if (!total || total <= 0) return "";
    const pct = Math.max(0, Math.min(100, (used / total) * 100));
    let cls = "";
    if (pct >= 90) cls = "crit";
    else if (pct >= 75) cls = "warn";
    return `<span class="meter">${label} ${_fmtGB(used)}/${_fmtGB(total)}`
        + `<span class="meter-bar"><span class="meter-fill ${cls}" style="width:${pct.toFixed(0)}%"></span></span>`
        + `</span>`;
}

function _renderComfyStats(stats) {
    const el = document.getElementById("comfy-health-stats");
    if (!el) return;
    if (!stats) {
        el.classList.remove("visible");
        el.innerHTML = "";
        return;
    }
    const dev = (stats.devices && stats.devices[0]) || {};
    const sys = stats.system || {};
    const vramUsed = (dev.vram_total || 0) - (dev.vram_free || 0);
    const ramUsed = (sys.ram_total || 0) - (sys.ram_free || 0);
    const cacheUsed = (dev.torch_vram_total || 0) - (dev.torch_vram_free || 0);
    const parts = [
        _buildMeter("VRAM", vramUsed, dev.vram_total),
        _buildMeter("RAM",  ramUsed,  sys.ram_total),
        _buildMeter("Cache", cacheUsed, dev.torch_vram_total),
    ].filter(Boolean).join("");
    if (parts) {
        el.innerHTML = parts;
        el.classList.add("visible");
    } else {
        el.classList.remove("visible");
        el.innerHTML = "";
    }
}

// Track consecutive failed connection probes so a single transient
// timeout (e.g. while ComfyUI is busy generating) doesn't immediately
// flip the indicator to red and panic the user.
let _comfyMissCount = 0;
const COMFY_MISS_THRESHOLD = 3;

async function checkComfyConnection() {
    try {
        const testRes = await fetch('/api/comfy_status');
        const data = await testRes.json();
        if (data.connected) {
            // Server returned a fresh success (or a "stale" cached one
            // during a transient ComfyUI hiccup — both count as alive).
            _comfyMissCount = 0;
            comfyDot.className = "dot green";
            comfyStatus.textContent = data.stale
                ? "ComfyUI: Connected (busy)"
                : "ComfyUI: Connected";
            _renderComfyStats(data.stats);
            // Body-level class: CSS cranks the title shimmer, lights up
            // the VRAM/RAM/cache meters with a steam sweep, and amps
            // chip glows while ComfyUI is actively rendering. `stale`
            // means the cached-success branch fired (ComfyUI is busy
            // enough to not answer /system_stats within 10s) — the
            // strongest live-generation signal we have without polling
            // /queue separately. Also, if the ComfyUI chip has an
            // advancing heartbeat, we pulse it too via markIfaceEngaged.
            document.body.classList.toggle('is-generating', !!data.stale);
            if (data.stale) { markIfaceEngaged('comfyui'); }
            // Mirror the result to _managedLive so the synthetic
            // ComfyUI chip in the Connected apps row goes green.
            (window._managedLive = window._managedLive || {}).comfyui = true;
        } else {
            // Server reports disconnected. Wait for THRESHOLD consecutive
            // misses before going red — single transient failures are
            // common when ComfyUI is mid-generation.
            _comfyMissCount += 1;
            if (_comfyMissCount >= COMFY_MISS_THRESHOLD) {
                comfyDot.className = "dot red";
                comfyStatus.textContent = "ComfyUI: Disconnected";
                _renderComfyStats(null);
                document.body.classList.remove('is-generating');
                (window._managedLive = window._managedLive || {}).comfyui = false;
            } else {
                comfyDot.className = "dot yellow";
                comfyStatus.textContent = "ComfyUI: Checking…";
            }
        }
    } catch(e) {
        _comfyMissCount += 1;
        if (_comfyMissCount >= COMFY_MISS_THRESHOLD) {
            comfyDot.className = "dot red";
            comfyStatus.textContent = "ComfyUI: Disconnected";
            _renderComfyStats(null);
            document.body.classList.remove('is-generating');
        } else {
            comfyDot.className = "dot yellow";
            comfyStatus.textContent = "ComfyUI: Checking…";
        }
    }
}

// ── Chip engagement pulse ────────────────────────────────────────────
// Flags a Connected-apps chip as "actively engaging with the Guild"
// for ~2.5s — CSS picks up .iface-engaged and applies a gold aura +
// rapid dot pulse on top of whatever online/stale/idle state it already
// has. Called from two places:
//   1. refreshActiveInterfaces() below — when an interface's last_meta
//      heartbeat timestamp advances since the previous poll (i.e. the
//      app just ping'd us), the chip pulses.
//   2. checkComfyConnection() — when ComfyUI is stale/busy, the
//      synthetic comfyui chip pulses while the job is in flight.
window._ifaceLastHeartbeat = window._ifaceLastHeartbeat || {};
window._ifaceEngageTimers = window._ifaceEngageTimers || {};
function markIfaceEngaged(key) {
    const chips = document.querySelectorAll(
        `.active-iface-chip[data-iface-key="${key}"]`);
    if (!chips.length) return;
    chips.forEach(c => c.classList.add('iface-engaged'));
    // Reset/extend the 2.5s window so back-to-back pulses stay lit
    // continuously rather than flickering.
    if (window._ifaceEngageTimers[key]) {
        clearTimeout(window._ifaceEngageTimers[key]);
    }
    window._ifaceEngageTimers[key] = setTimeout(() => {
        document.querySelectorAll(
            `.active-iface-chip[data-iface-key="${key}"]`
        ).forEach(c => c.classList.remove('iface-engaged'));
        delete window._ifaceEngageTimers[key];
    }, 2500);
}

// Kicks the server-side probes for SillyTavern + Signal Bridge. The
// server's endpoints call interface_registry.heartbeat(...) on success,
// so whichever of those two apps is actually up appears as a chip in
// the "Connected apps" row. No DOM touched here.
async function checkSillyTavernConnection() {
    try { await fetch('/api/sillytavern_status'); }
    catch (_e) { /* ignored — chip stays absent */ }
}

async function checkSignalBridgeConnection() {
    try { await fetch('/api/signal_bridge_status'); }
    catch (_e) { /* ignored — chip stays absent */ }
}

// ── Active interfaces (cross-interface backbone) ──────────────────
// Polls /api/interfaces and renders a chip row for each interface the
// Guild registry reports as installed + enabled + online. No dead chips
// — an uninstalled or offline interface simply doesn't appear here.
//
// `window.activeInterfaces` is the source of truth consumed by the
// starter-chip and image-action-chip renderers, so a "Send to Resolve"
// chip only appears when Resolve is actually there.
window.activeInterfaces = {};   // key -> snapshot dict
window.activeInterfacesKeys = []; // ordered list of active keys
window.networkSurvey = {};       // key -> declared-placement record

async function refreshActiveInterfaces() {
    // Fetch the network survey in parallel — it holds the user's declared
    // placement per service (which machine they WANT to use). We overlay
    // that onto the live heartbeat state so a chip reflects the user's
    // pick even when a remote antenna is still heartbeating the old path.
    // Response shape: { catalog: {...}, survey: {key: {placement, host, ...}}, ready: bool }
    try {
        const sres = await fetch('/api/spellcaster/network/survey');
        if (sres.ok) {
            const sdata = await sres.json();
            window.networkSurvey = sdata.survey || sdata.services || sdata || {};
        }
    } catch (_e) { /* survey optional */ }
    try {
        const res = await fetch('/api/interfaces');
        if (!res.ok) {
            if (res.status === 501) return; // backbone disabled — skip silently
            throw new Error(`HTTP ${res.status}`);
        }
        const data = await res.json();
        const ifaces = data.interfaces || {};
        // We want to SEE every interface the Guild has ever heard from,
        // not just the perfect-installed-and-online triplet. Keep any
        // interface the user enabled and that either:
        //   - is installed somewhere (local plugin or on a remote antenna),
        //   - or is heartbeating right now (online=true via remote),
        //   - or has heartbeated recently (last_heartbeat within 5 min).
        // Skip the Guild's self-entry — it's the thing rendering the UI.
        const NOW_S = Date.now() / 1000;
        const RECENT_S = 300;
        const active = {};
        const keys = [];
        for (const [k, v] of Object.entries(ifaces)) {
            if (k === 'guild' || k === 'antenna') continue;
            if (!v.enabled) continue;
            const recent = (v.last_heartbeat || 0) > NOW_S - RECENT_S;
            if (v.installed || v.online || recent) {
                active[k] = v;
                keys.push(k);
                // Engagement pulse: heartbeat moved forward since the
                // last refresh → this interface just talked to us.
                // First observation doesn't count (we have nothing to
                // compare to). markIfaceEngaged schedules itself for
                // after the DOM is updated below via a 0ms timeout.
                const prev = window._ifaceLastHeartbeat[k] || 0;
                const curr = v.last_heartbeat || 0;
                if (prev && curr > prev) {
                    setTimeout(() => markIfaceEngaged(k), 0);
                }
                if (curr) window._ifaceLastHeartbeat[k] = curr;
            }
        }
        // Synthesize chips for managed services (ComfyUI / Ollama /
        // Kobold). These are backend engines, not frontends, so they
        // don't heartbeat to /api/interfaces — but the user still
        // needs to hit their ⚡ Start button on them.
        // Inject synthetic rows so the chip renders regardless of
        // reachability; the sidebar's other pollers already drive the
        // green/idle state via window._managedLive below.
        const managedDefs = [
            { key: 'comfyui',     label: 'ComfyUI',      icon: '🎨' },
            { key: 'ollama',      label: 'Ollama',       icon: '🦙' },
            { key: 'kobold_rp',   label: 'Kobold · RP',  icon: '📜' },
            { key: 'kobold_tts',  label: 'Kobold · TTS', icon: '🎙️' },
        ];
        const managedLive = window._managedLive || {};
        for (const m of managedDefs) {
            if (active[m.key]) continue;  // already in interfaces
            const live = !!managedLive[m.key];
            active[m.key] = {
                enabled: true,
                online: live,
                online_local: live,
                origin: 'local',
                last_heartbeat: live ? (Date.now() / 1000) : 0,
                capabilities: [],
                ui_label: m.label,
                icon: m.icon,
                last_meta: {},
                managed: true,
            };
            keys.push(m.key);
        }
        // Pin ComfyUI at the top of the Connected apps row. It's the
        // service the user interacts with most (every generation goes
        // through it), so the chip should always be the first thing
        // the eye lands on. Other chips keep their natural order.
        keys.sort((a, b) => {
            if (a === 'comfyui') return -1;
            if (b === 'comfyui') return 1;
            return 0;
        });
        window.activeInterfaces = active;
        window.activeInterfacesKeys = keys;
        renderActiveInterfaceChips();
    } catch (e) {
        // Silent — the feature is optional. Hide the strip.
        window.activeInterfaces = {};
        window.activeInterfacesKeys = [];
        renderActiveInterfaceChips();
    }
}

// Per-app control matrix, refreshed alongside interfaces. Shape:
//   { comfyui: {target:"theo"}, ollama: {target:"local"}, ... }
// The ⚡ Start button calls /api/app_control/start, which reads this
// matrix's `target` to pick the host (local subprocess or antenna).
window.appControlMatrix = window.appControlMatrix || {};
async function refreshAppControlMatrix() {
    try {
        const r = await fetch('/api/app_control/config');
        if (!r.ok) return;
        const d = await r.json();
        window.appControlMatrix = d.app_control || {};
    } catch (e) { /* silent — chips fall back to blank toggles */ }
}

function renderActiveInterfaceChips() {
    const container = document.getElementById('active-interfaces-container');
    const row = document.getElementById('active-interfaces-row');
    if (!container || !row) return;
    const keys = window.activeInterfacesKeys || [];
    if (keys.length === 0) {
        container.style.display = 'none';
        row.innerHTML = '';
        return;
    }
    container.style.display = '';
    const NOW_S = Date.now() / 1000;
    row.innerHTML = '';
    for (const k of keys) {
        const v = window.activeInterfaces[k];
        const label = v.ui_label || k;
        const icon = v.icon || '🔌';
        const age = NOW_S - (v.last_heartbeat || 0);
        const meta = v.last_meta || {};
        const caps = (v.capabilities || []).join(', ');

        // User's declared placement for this service (from /network/survey).
        // When present, it wins over the heartbeat-derived origin — the
        // chip should show where the user TOLD us to run it, not where
        // a leftover heartbeat is still coming from.
        const decl = (window.networkSurvey || {})[k] || null;
        let origin, host, statusTxt, cls, subTip;
        if (decl && decl.placement) {
            origin = decl.placement === 'local' ? 'local'
                   : decl.placement === 'remote' ? 'remote'
                   : decl.placement;   // not_installed / skip / unknown
            if (origin === 'local') {
                host = 'this machine';
                const localOn = v.online_local || (v.origin === 'local' && v.online);
                cls = localOn ? 'online' : (age < 300 ? 'stale' : 'idle');
                statusTxt = localOn ? 'online on this machine'
                          : 'declared local — no heartbeat yet';
            } else if (origin === 'remote') {
                host = decl.host || meta.ip || meta.machine || 'remote';
                const remoteOn = v.online_remote && (!decl.host || meta.ip === decl.host);
                cls = remoteOn ? 'online' : (age < 300 ? 'stale' : 'idle');
                statusTxt = remoteOn ? `online on ${host}`
                          : `declared remote (${host}) — no heartbeat yet`;
            } else {
                host = origin === 'not_installed' ? 'skipped' : origin;
                cls = 'idle';
                statusTxt = origin === 'not_installed' ? 'not installed'
                          : 'unknown placement';
            }
            subTip = decl.verified ? 'verified reachable' : 'not yet verified';
        } else {
            // No declared placement — fall back to heartbeat origin.
            origin = v.origin || (v.online_remote ? 'remote'
                                  : v.online_local ? 'local' : 'none');
            host = meta.machine || meta.ip
                   || (origin === 'local' ? 'this machine' : '');
            cls = v.online ? 'online' : (age < 300 ? 'stale' : 'idle');
            statusTxt = v.online ? 'online' : (age < 300 ? 'recently seen' : 'idle');
            subTip = 'no declared placement';
        }

        const tipParts = [`${label}: ${statusTxt}`];
        if (caps) tipParts.push(caps);
        tipParts.push(subTip);
        tipParts.push('(click to change where this app runs)');
        const tooltip = tipParts.join(' · ');

        const chip = document.createElement('span');
        chip.className = `active-iface-chip iface-${cls} iface-${origin}`;
        chip.title = tooltip;
        chip.dataset.ifaceKey = k;
        chip.dataset.ifaceLabel = label;
        // Manual launch button (⚡) — no auto-start. The user asked for
        // explicit-only launch; the old 🔁 auto toggle and its boot-time
        // plumbing were removed so nothing runs behind the user's back.
        const managed = (k === 'comfyui' || k === 'ollama' ||
                          k === 'kobold' || k === 'kobold_rp' ||
                          k === 'kobold_tts');
        const startTip = managed
            ? 'Start this app on its target machine now'
            : 'This app has no managed launcher yet';
        chip.innerHTML =
            `<span class="iface-toggles">` +
                `<button type="button" class="iface-toggle-btn iface-start-btn"` +
                    ` data-app="${k}"` +
                    ` title="${startTip}"` +
                    (managed ? '' : ' disabled') + '>⚡</button>' +
            `</span>` +
            `<span class="iface-icon">${icon}</span>` +
            `<span class="iface-label">${label}</span>` +
            (host ? `<span class="iface-host">${host}</span>` : '');
        chip.addEventListener('click', (ev) => {
            // Let toggle buttons handle their own clicks without opening
            // the placement popover underneath.
            const btn = ev.target.closest && ev.target.closest('.iface-toggle-btn');
            if (btn) { ev.stopPropagation(); return; }
            ev.stopPropagation();
            openIfacePlacementMenu(chip, k, label, v);
        });
        // Wire the manual Start button.
        const startBtn = chip.querySelector('.iface-start-btn');
        if (startBtn && managed) {
            startBtn.addEventListener('click', async (ev) => {
                ev.stopPropagation();
                startBtn.disabled = true;
                startBtn.textContent = '⏳';
                try {
                    const r = await fetch('/api/app_control/start', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({app: k}),
                    });
                    const d = await r.json();
                    if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
                    startBtn.textContent = (d.state === 'already_running') ? '✓' : '⚡';
                } catch (e) {
                    startBtn.textContent = '⚠';
                    startBtn.title = `Start failed: ${e.message || e}`;
                }
                setTimeout(() => { startBtn.textContent = '⚡'; startBtn.disabled = false; }, 2500);
            });
        }
        row.appendChild(chip);
    }
}

// ── Placement popover ─────────────────────────────────────────────────
// Clicking an interface chip opens a small menu listing every available
// host for that service (localhost + each antenna). Picking one POSTs
// to /api/spellcaster/network/declare which persists the choice to
// survey.json and probes the new placement. The chip row refreshes
// on the next /api/interfaces tick so state propagates cleanly.
let _ifaceMenuEl = null;

function _closeIfacePlacementMenu() {
    if (_ifaceMenuEl && _ifaceMenuEl.parentNode) {
        _ifaceMenuEl.parentNode.removeChild(_ifaceMenuEl);
    }
    _ifaceMenuEl = null;
    document.removeEventListener('click', _closeIfacePlacementMenu);
}

async function openIfacePlacementMenu(anchorEl, ifaceKey, ifaceLabel, iface) {
    _closeIfacePlacementMenu();
    // Collect option list: localhost + each antenna that advertises this service
    // or could run it. We trust the user: any antenna can in principle host
    // any service, but we surface antennas that CURRENTLY declare / detect
    // the service first, then offer the rest as "point this elsewhere" too.
    let antennas = [];
    try {
        const resp = await fetch('/api/antennas');
        if (resp.ok) antennas = (await resp.json()).antennas || [];
    } catch (_e) { /* offline — localhost-only menu */ }

    // "Current" = user's declared placement (persisted via
    // /network/declare), not the heartbeat origin. Heartbeats are a
    // discovery signal; the survey is what the user wants the Guild
    // to actually use.
    const decl = (window.networkSurvey || {})[ifaceKey] || {};
    const currentPlacement = decl.placement
        || iface.origin
        || (iface.online_remote ? 'remote'
            : iface.online_local ? 'local' : 'unknown');
    const currentHost = decl.host
        || (iface.last_meta || {}).ip
        || (iface.last_meta || {}).machine || '';

    const menu = document.createElement('div');
    menu.className = 'iface-placement-menu';
    menu.innerHTML =
        `<div class="iface-menu-header">Run <b>${ifaceLabel}</b> on…</div>`;

    // Escape HTML so hostnames / errors can't inject markup
    const esc = s => String(s || '')
        .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;').replaceAll('"', '&quot;');

    const addOption = (iconChar, label, sub, pill, pillClass,
                        placement, host, port, antenna_port, current) => {
        const opt = document.createElement('button');
        opt.type = 'button';
        opt.className = 'iface-menu-option' + (current ? ' current' : '');
        opt.innerHTML =
            `<span class="opt-mark">${current ? '✓' : esc(iconChar)}</span>` +
            `<span class="opt-body">` +
                `<span class="opt-label">${esc(label)}</span>` +
                (sub ? `<span class="opt-sub">${esc(sub)}</span>` : '') +
            `</span>` +
            (pill
                ? `<span class="opt-pill ${pillClass || ''}">${esc(pill)}</span>`
                : '');
        opt.addEventListener('click', async (ev) => {
            ev.stopPropagation();
            opt.classList.add('pending');
            opt.innerHTML =
                `<span class="opt-mark">…</span>` +
                `<span class="opt-body">` +
                    `<span class="opt-label">Switching to ${esc(label)}</span>` +
                    `<span class="opt-sub">contacting ${esc(placement)}…</span>` +
                `</span>`;
            const body = { key: ifaceKey, placement };
            if (host) body.host = host;
            if (port) body.port = port;
            if (antenna_port) body.antenna_port = antenna_port;
            try {
                const r = await fetch('/api/spellcaster/network/declare', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await r.json().catch(() => ({}));
                if (!r.ok || data.error) {
                    opt.innerHTML =
                        `<span class="opt-mark">✗</span>` +
                        `<span class="opt-body">` +
                            `<span class="opt-label">Failed</span>` +
                            `<span class="opt-sub">${esc(data.error || ('HTTP ' + r.status))}</span>` +
                        `</span>` +
                        `<span class="opt-pill danger">error</span>`;
                    return;
                }
                _closeIfacePlacementMenu();
                refreshActiveInterfaces();
                refreshAntennas();
            } catch (e) {
                opt.innerHTML =
                    `<span class="opt-mark">✗</span>` +
                    `<span class="opt-body">` +
                        `<span class="opt-label">Failed</span>` +
                        `<span class="opt-sub">${esc(e.message || String(e))}</span>` +
                    `</span>` +
                    `<span class="opt-pill danger">error</span>`;
            }
        });
        menu.appendChild(opt);
    };

    // Option 1: this machine (localhost)
    addOption('🖥', 'This machine', 'localhost',
              null, null,
              'local', '', 0, 0,
              currentPlacement === 'local');

    // Options 2..N: each registered antenna.
    for (const a of antennas) {
        const supports = (a.services || []).includes(ifaceKey);
        const detail = (a.services_detail || {})[ifaceKey] || {};
        const reachable = detail.reachable === true;
        const host = a.ip || a.hostname || '';
        const pill = supports
            ? (reachable ? 'reachable' : 'declared')
            : 'paired';
        const pillClass = supports
            ? (reachable ? 'reachable' : 'declared')
            : '';
        addOption('📡',
                  a.hostname || host || 'remote',
                  host,
                  pill, pillClass,
                  'remote',
                  a.ip || '', 0, 7334,
                  currentPlacement === 'remote' && currentHost === a.ip);
    }

    // Option N+1: skip this service entirely
    addOption('⊘', 'Skip (not installed)', 'don\u2019t route here',
              null, null,
              'not_installed', '', 0, 0,
              currentPlacement === 'not_installed');

    // Position below the chip
    const rect = anchorEl.getBoundingClientRect();
    menu.style.position = 'fixed';
    menu.style.top = (rect.bottom + 6) + 'px';
    menu.style.left = Math.min(rect.left, window.innerWidth - 260) + 'px';
    document.body.appendChild(menu);
    _ifaceMenuEl = menu;
    // Close on any outside click (next tick so the opening click doesn't
    // re-trigger the handler).
    setTimeout(() => {
        document.addEventListener('click', _closeIfacePlacementMenu);
    }, 0);
}

// ── Pair-code dialog ──────────────────────────────────────────────────
// Opens a modal overlay with two inputs: the antenna's IP and the
// 6-digit pair code its tray is currently showing. POSTs to
// /api/antennas/pair which forwards to the antenna's /pair/claim,
// receives the real bearer token, and persists it into guild config.
function openAntennaPairDialog() {
    if (document.getElementById('pair-antenna-overlay')) return;
    const overlay = document.createElement('div');
    overlay.id = 'pair-antenna-overlay';
    overlay.className = 'pair-overlay';
    overlay.innerHTML = `
        <div class="pair-modal" role="dialog" aria-modal="true">
            <div class="pair-header">
                <span class="pair-title">Pair a new antenna</span>
                <button type="button" class="pair-close" title="Close">&times;</button>
            </div>
            <div class="pair-body">
                <p class="pair-hint">
                    On the other machine, open the antenna's tray icon
                    and click <b>Pair with Guild</b>. A 6-digit code will
                    appear. Type the machine's IP and that code below.
                </p>
                <label class="pair-field">
                    <span>Machine IP or hostname</span>
                    <input type="text" id="pair-host-input"
                           placeholder="192.168.1.42 (no http://)"
                           autocomplete="off">
                    <small class="pair-subhint">Just the IP or hostname. The scheme (http / https) and port are handled for you.</small>
                </label>
                <label class="pair-field">
                    <span>6-digit pair code</span>
                    <input type="text" id="pair-code-input"
                           placeholder="123456" inputmode="numeric"
                           maxlength="9" autocomplete="one-time-code">
                </label>
                <div class="pair-row">
                    <label class="pair-port-field">
                        <span>Port</span>
                        <input type="number" id="pair-port-input" value="7334" min="1" max="65535">
                    </label>
                    <div class="pair-row-spacer"></div>
                </div>
                <div id="pair-status" class="pair-status"></div>
                <div class="pair-actions">
                    <button type="button" class="pair-cancel">Cancel</button>
                    <button type="button" class="pair-submit">Pair antenna</button>
                </div>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    const hostEl   = overlay.querySelector('#pair-host-input');
    const codeEl   = overlay.querySelector('#pair-code-input');
    const portEl   = overlay.querySelector('#pair-port-input');
    const statusEl = overlay.querySelector('#pair-status');
    const submitBtn= overlay.querySelector('.pair-submit');
    const cancelBtn= overlay.querySelector('.pair-cancel');
    const closeBtn = overlay.querySelector('.pair-close');

    const close = () => overlay.remove();
    cancelBtn.addEventListener('click', close);
    closeBtn .addEventListener('click', close);
    overlay.addEventListener('click', (ev) => { if (ev.target === overlay) close(); });
    // Pre-fill host if there's already an antenna registered
    try {
        const existing = Object.values(window.activeInterfaces || {})
            .find(v => (v.last_meta || {}).ip);
        if (existing) hostEl.value = existing.last_meta.ip || '';
    } catch (_e) { /* best-effort */ }

    // Numeric-only code input. Allow common separators, strip on submit.
    codeEl.addEventListener('input', () => {
        codeEl.value = codeEl.value.replace(/[^0-9 \-]/g, '').slice(0, 9);
    });
    hostEl.focus();

    const submit = async () => {
        let host = (hostEl.value || '').trim();
        // Strip any scheme + trailing slash the user typed. The server
        // does this too (belt-and-suspenders) but doing it here keeps
        // the status line readable ("Contacting 192.168.x.y:7334…"
        // rather than "Contacting http://192.168.x.y:7334:7334…").
        let port = parseInt(portEl.value, 10) || 7334;
        try {
            if (/^https?:\/\//i.test(host)) {
                const u = new URL(host);
                host = u.hostname;
                if (u.port) port = parseInt(u.port, 10) || port;
            } else if (host.split(':').length === 2) {
                const [h, p] = host.split(':');
                if (/^\d+$/.test(p)) { host = h; port = parseInt(p, 10); }
            }
            host = host.replace(/\/+$/, '');
        } catch (_e) { /* let server handle bad input */ }
        const code = (codeEl.value || '').replace(/[ \-]/g, '').trim();
        if (!host) { statusEl.className = 'pair-status error'; statusEl.textContent = 'Machine IP or hostname required.'; return; }
        if (!/^\d{6}$/.test(code)) {
            statusEl.className = 'pair-status error';
            statusEl.textContent = 'Pair code must be exactly 6 digits.';
            return;
        }
        submitBtn.disabled = true;
        submitBtn.textContent = 'Pairing…';
        statusEl.className = 'pair-status';
        statusEl.textContent = `Contacting ${host}:${port}…`;
        // Reflect any auto-strip back into the visible inputs so the
        // user understands what we sent.
        hostEl.value = host;
        portEl.value = String(port);
        try {
            const r = await fetch('/api/antennas/pair', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ host, code, port }),
            });
            const data = await r.json().catch(() => ({}));
            if (!r.ok) {
                statusEl.className = 'pair-status error';
                statusEl.textContent = data.error || `HTTP ${r.status}`;
                submitBtn.disabled = false;
                submitBtn.textContent = 'Pair antenna';
                return;
            }
            statusEl.className = 'pair-status success';
            statusEl.textContent = `Paired with ${data.host}. Refreshing…`;
            // Kick both strips so the new antenna appears quickly.
            refreshActiveInterfaces();
            refreshAntennas();
            setTimeout(close, 700);
        } catch (e) {
            statusEl.className = 'pair-status error';
            statusEl.textContent = e.message || String(e);
            submitBtn.disabled = false;
            submitBtn.textContent = 'Pair antenna';
        }
    };
    submitBtn.addEventListener('click', submit);
    // Enter in either input submits
    [hostEl, codeEl, portEl].forEach(el => {
        el.addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter') { ev.preventDefault(); submit(); }
            if (ev.key === 'Escape') { ev.preventDefault(); close(); }
        });
    });
}

// ── Antennas (remote-machine agents) ──────────────────────────────────
// Polls /api/antennas and renders one chip per remote machine running an
// antenna. Each chip shows hostname + IP + declared/detected services.
// Clicking a chip could open the antenna's diagnostic in the future;
// today it's a visible signal that a remote GPU is paired.
async function refreshAntennas() {
    try {
        const res = await fetch('/api/antennas');
        if (!res.ok) return;
        const data = await res.json();
        renderAntennaChips(data.antennas || []);
    } catch (e) {
        renderAntennaChips([]);
    }
}

function renderAntennaChips(antennas) {
    const container = document.getElementById('connected-antennas-container');
    const row = document.getElementById('connected-antennas-row');
    if (!container || !row) return;
    // Container stays visible (never display:none) so the "+ Pair new"
    // button is always reachable — the old "hide if empty" hid the
    // handshake UI too. When there are no antennas we show a subtle
    // placeholder row instead.
    container.style.display = '';
    if (!Array.isArray(antennas) || antennas.length === 0) {
        row.innerHTML = `<span class="antenna-empty-hint">no antennas paired yet</span>`;
        return;
    }
    const NOW_S = Date.now() / 1000;
    const html = antennas.map(a => {
        const host = a.hostname || a.ip || '?';
        const ip = a.ip || '';
        const services = a.services || [];
        const detail = a.services_detail || {};
        const age = NOW_S - (a.last_heartbeat || 0);
        const cls = a.online ? 'online' : (age < 300 ? 'stale' : 'idle');
        // Build per-service list with reachability where known.
        const svcLines = services.map(s => {
            const d = detail[s] || {};
            let note = '';
            if (d.reachable === true)  note = '✓';
            if (d.reachable === false) note = '✗';
            if (d.declared === true && !('reachable' in d)) note = '·';
            if (s === 'comfyui' && d.vram_free_gb != null && d.vram_total_gb != null) {
                note += ` (${d.vram_free_gb.toFixed(1)}/${d.vram_total_gb.toFixed(1)} GB free)`;
            }
            return `${s}${note ? ' ' + note : ''}`;
        });
        const tooltip = (
            `Antenna: ${host}\n` +
            (ip ? `IP: ${ip}\n` : '') +
            `Status: ${a.online ? 'online' : (age < 300 ? 'recently seen' : 'idle')}\n` +
            (svcLines.length ? `Services:\n  ${svcLines.join('\n  ')}` : '')
        ).replace(/"/g, '&quot;');
        const count = services.length;
        return `<span class="antenna-chip antenna-${cls}"
                       data-host="${host}" title="${tooltip}">
                  <span class="antenna-icon">📡</span>
                  <span class="antenna-host">${host}</span>
                  <span class="antenna-count">${count}</span>
                </span>`;
    }).join('');
    row.innerHTML = html;
    // Right-click on any antenna chip → "Connect an app" popover so
    // the user can tell that antenna where a specific plugin (GIMP,
    // ComfyUI, SillyTavern, …) lives on that machine. The popover
    // submits to /api/app_control/register which proxies to the
    // antenna's /service/register endpoint.
    row.querySelectorAll('.antenna-chip').forEach(chip => {
        chip.addEventListener('contextmenu', (ev) => {
            ev.preventDefault();
            openConnectAppMenu({
                anchor: chip,
                target: chip.dataset.host,
                targetLabel: chip.dataset.host || 'antenna',
            });
        });
    });
}

// ── Connect-an-app popover (right-click on antenna chip) ─────────────
// Lists every plugin type Spellcaster knows about, with an icon + one-
// line hint. Clicking a type opens a tiny modal asking for the local
// launcher path / exe path on the target machine. The chosen path
// POSTs to /api/app_control/register which persists it either to
// guild_config.app_control (when target === 'local') or to the
// paired antenna's antenna_config.json (remote).

// Per-app metadata — icon, human label, placeholder hint for the
// launcher field. Keep the list short + ordered so the popover reads
// top-to-bottom as "image engine first, frontend tools next".
const _CONNECT_APP_TYPES = [
    { key: 'comfyui',    icon: '🎨', label: 'ComfyUI',
      hint: 'path to launch.bat / launch_optimized.bat / python main.py',
      example: 'C:/tools/ComfyUI/launch_optimized.bat' },
    { key: 'ollama',     icon: '🦙', label: 'Ollama',
      hint: 'path to ollama.exe (leave blank for PATH lookup)',
      example: 'ollama' },
    { key: 'kobold',     icon: '📜', label: 'KoboldCpp (chat/RP)',
      hint: 'path to koboldcpp.exe + optional model gguf',
      example: 'C:/tools/koboldcpp/koboldcpp.exe' },
    { key: 'kobold_tts', icon: '🎙️', label: 'Kobold · TTS / STT',
      hint: 'hostname:port (e.g. 192.168.x.x:5002) — OR full http:// URL',
      example: '192.168.x.x:5002' },
    { key: 'gimp',       icon: '🎨', label: 'GIMP',
      hint: 'path to gimp-3.0.exe / gimp.exe',
      example: 'C:/Program Files/GIMP 3/bin/gimp-3.0.exe' },
    { key: 'darktable',  icon: '📸', label: 'Darktable',
      hint: 'path to darktable.exe',
      example: 'C:/Program Files/darktable/bin/darktable.exe' },
    { key: 'resolve',    icon: '🎬', label: 'Resolve',
      hint: 'path to Resolve.exe',
      example: 'C:/Program Files/Blackmagic Design/DaVinci Resolve/Resolve.exe' },
    { key: 'sillytavern',icon: '🍺', label: 'SillyTavern',
      hint: 'path to Start.bat',
      example: 'C:/tools/SillyTavern/Start.bat' },
    { key: 'signal',     icon: '💬', label: 'Signal Bridge',
      hint: 'path to signal-bridge launcher',
      example: 'C:/tools/signal-bridge/run.bat' },
];

let _connectMenuEl = null;
function _closeConnectAppMenu() {
    if (_connectMenuEl && _connectMenuEl.parentNode) {
        _connectMenuEl.parentNode.removeChild(_connectMenuEl);
    }
    _connectMenuEl = null;
    document.removeEventListener('click', _closeConnectAppMenu);
}

function openConnectAppMenu(opts) {
    _closeConnectAppMenu();
    const { anchor, target, targetLabel } = opts || {};
    const menu = document.createElement('div');
    menu.className = 'connect-app-menu';
    menu.innerHTML = `
        <div class="connect-app-menu-title">
            Connect an app on <b>${targetLabel}</b>
        </div>
        <div class="connect-app-menu-list">
            ${_CONNECT_APP_TYPES.map(t => `
                <button type="button" class="connect-app-item"
                        data-app="${t.key}">
                    <span class="connect-app-icon">${t.icon}</span>
                    <span class="connect-app-meta">
                        <span class="connect-app-label">${t.label}</span>
                        <span class="connect-app-hint">${t.hint}</span>
                    </span>
                </button>`).join('')}
        </div>`;
    // Anchor near the chip that triggered the menu; clamp to viewport.
    const rect = anchor
        ? anchor.getBoundingClientRect()
        : { left: 200, top: 200, bottom: 200, height: 0 };
    menu.style.left = `${rect.left}px`;
    menu.style.top  = `${rect.bottom + 6}px`;
    document.body.appendChild(menu);
    // Clamp overflow AFTER measuring
    const mr = menu.getBoundingClientRect();
    if (mr.right > window.innerWidth - 8) {
        menu.style.left = `${Math.max(8, window.innerWidth - mr.width - 8)}px`;
    }
    if (mr.bottom > window.innerHeight - 8) {
        menu.style.top = `${Math.max(8, rect.top - mr.height - 6)}px`;
    }
    _connectMenuEl = menu;
    // Click outside closes. Defer one tick so the current contextmenu
    // tap doesn't immediately dismiss it.
    setTimeout(() => document.addEventListener('click', _closeConnectAppMenu), 0);
    menu.addEventListener('click', ev => ev.stopPropagation());
    menu.querySelectorAll('.connect-app-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const appKey = btn.dataset.app;
            const spec = _CONNECT_APP_TYPES.find(t => t.key === appKey);
            _closeConnectAppMenu();
            _openConnectAppDialog(spec, target, targetLabel);
        });
    });
}

function _openConnectAppDialog(spec, target, targetLabel) {
    // Simple prompt for the launcher path. Avoids a heavier modal;
    // the input is single-field, submits on Enter, cancels on Esc.
    const overlay = document.createElement('div');
    overlay.className = 'connect-app-overlay';
    overlay.innerHTML = `
        <div class="connect-app-dialog">
            <div class="connect-app-dialog-head">
                ${spec.icon} Connect <b>${spec.label}</b>
                <small>on ${targetLabel}</small>
            </div>
            <label class="connect-app-field">
                <span>Launcher path</span>
                <input type="text" class="connect-app-launcher"
                       placeholder="${spec.example}"
                       autofocus>
            </label>
            <div class="connect-app-dialog-hint">${spec.hint}</div>
            <div class="connect-app-dialog-actions">
                <button type="button" class="connect-app-cancel">Cancel</button>
                <button type="button" class="connect-app-save">Save</button>
            </div>
            <div class="connect-app-dialog-status"></div>
        </div>`;
    document.body.appendChild(overlay);
    const input = overlay.querySelector('.connect-app-launcher');
    const status = overlay.querySelector('.connect-app-dialog-status');
    const close = () => overlay.remove();
    const submit = async () => {
        const raw = input.value.trim();
        if (!raw) {
            status.textContent = 'Enter a value first.';
            return;
        }
        status.textContent = 'Saving…';
        // R139: kobold_tts takes a network location (URL or host:port),
        // not a filesystem path. Parse the user's input so we send a
        // well-shaped body to /api/app_control/register — the server
        // resolver then builds the full URL from host+port.
        const payload = {
            app: spec.key,
            target: target || 'local',
        };
        if (spec.key === 'kobold_tts') {
            let txt = raw;
            if (/^https?:\/\//i.test(txt)) {
                // Full URL — pass through as `url`; resolver's first
                // precedence tier uses it verbatim.
                payload.url = txt.replace(/\/+$/, '');
            } else {
                // Strip any leading scheme the user might've typed
                // without the colon (e.g. "https//" typos)
                txt = txt.replace(/^https?[:/]+/i, '');
                const [hostPart, portPart] = txt.split(':');
                payload.host = hostPart;
                if (portPart) {
                    const p = parseInt(portPart, 10);
                    if (!Number.isNaN(p)) payload.port = p;
                }
            }
            // Marker launcher so the entry is visible in app_control
            // (register endpoint requires a non-empty launcher).
            payload.launcher = payload.url || `${payload.host}:${payload.port || 5002}`;
        } else {
            payload.launcher = raw;
        }
        try {
            const r = await fetch('/api/app_control/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const d = await r.json();
            if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
            status.textContent = '✓ saved';
            setTimeout(close, 700);
        } catch (e) {
            status.textContent = `✗ ${e.message || e}`;
        }
    };
    overlay.querySelector('.connect-app-cancel').addEventListener('click', close);
    overlay.querySelector('.connect-app-save').addEventListener('click', submit);
    overlay.addEventListener('click', ev => {
        if (ev.target === overlay) close();
    });
    input.addEventListener('keydown', ev => {
        if (ev.key === 'Enter') { ev.preventDefault(); submit(); }
        if (ev.key === 'Escape') close();
    });
}

// Expose so other modules (the Guild tray redirect, for example)
// can trigger the same flow with target='local'.
window.openConnectAppMenu = openConnectAppMenu;

// Auto-open the local Connect-an-app flow when the URL carries
// `?connect_app=1` — used by the Guild tray's "Connect an app…" menu
// item so the user lands straight in the picker without hunting.
(function _maybeAutoOpenConnectApp() {
    try {
        const qs = new URLSearchParams(window.location.search);
        if (qs.get('connect_app') !== '1') return;
        // Defer to next tick so the rest of the bootstrap runs first.
        setTimeout(() => {
            openConnectAppMenu({
                anchor: null,
                target: 'local',
                targetLabel: 'this machine',
            });
            // Clean the query-string so a refresh doesn't reopen the menu.
            try {
                const url = new URL(window.location.href);
                url.searchParams.delete('connect_app');
                window.history.replaceState({}, '', url.toString());
            } catch (e) {}
        }, 600);
    } catch (e) {}
})();

// Exposed so starter_chips.js and image-action renderers can filter by it
window.isInterfaceActive = function(key) {
    return !!(window.activeInterfaces && window.activeInterfaces[key]);
};

// ── Recent assets across every interface ──────────────────────────
// The shared asset gallery (/api/assets) collects images from every
// Spellcaster frontend. We render the last N image assets as thumbnails
// in the sidebar. Clicking a thumb "uses" the asset — dropping it as a
// reference into the currently-active wizard's chat.

window._recentAssets = [];          // ordered by ts descending
window._recentAssetLimit = 9;       // 3x3 grid
window._recentAssetSSE = null;      // EventSource handle, re-created on need

async function refreshRecentAssets() {
    try {
        const res = await fetch('/api/assets?limit=' + window._recentAssetLimit);
        if (!res.ok) {
            if (res.status === 501) return; // gallery disabled
            throw new Error('HTTP ' + res.status);
        }
        const data = await res.json();
        const assets = (data.assets || []).filter(a =>
            a && a.mime && a.mime.startsWith('image/'));
        window._recentAssets = assets;
        renderRecentAssets();
    } catch (e) {
        // Silent — the widget is optional
    }
}

function renderRecentAssets() {
    const container = document.getElementById('recent-assets-container');
    const row = document.getElementById('recent-assets-row');
    if (!container || !row) return;
    const assets = window._recentAssets || [];
    if (assets.length === 0) {
        container.style.display = 'none';
        row.innerHTML = '';
        return;
    }
    container.style.display = '';
    row.innerHTML = '';
    for (const a of assets) {
        const thumb = document.createElement('div');
        thumb.className = 'recent-asset-thumb';
        thumb.dataset.hash = a.hash;
        thumb.style.backgroundImage = "url('/api/assets/" + a.hash + "')";
        const tooltipTitle = a.title || a.prompt || '';
        const tooltip = `${_originLabel(a.origin)}${tooltipTitle ? ' · ' + tooltipTitle : ''}`;
        thumb.title = tooltip;
        const badge = document.createElement('span');
        badge.className = 'recent-asset-origin-badge';
        badge.textContent = _originIcon(a.origin);
        thumb.appendChild(badge);
        thumb.addEventListener('click', () => _onRecentAssetClick(a));
        row.appendChild(thumb);
    }
}

function _originIcon(origin) {
    const icons = {
        guild: '💬',
        gimp: '🖼️',
        darktable: '📷',
        resolve: '🎬',
        sillytavern: '🎭',
        signal: '📱',
    };
    return icons[origin] || '🔌';
}

function _originLabel(origin) {
    const labels = {
        guild: 'Wizard Guild',
        gimp: 'GIMP',
        darktable: 'Darktable',
        resolve: 'Resolve',
        sillytavern: 'SillyTavern',
        signal: 'Signal',
    };
    return labels[origin] || origin || 'unknown';
}

function _onRecentAssetClick(asset) {
    // Drop the asset into the active wizard's chat as an image
    // reference. Uses the same pending-attachment mechanism cross-
    // wizard chips use — adds a user-side attachment bubble with the
    // thumbnail, then fires an LLM message referring to it.
    if (!asset || !asset.hash) return;
    const absUrl = window.location.origin + '/api/assets/' + asset.hash;
    if (typeof _renderPendingAttachment === 'function') {
        _renderPendingAttachment({
            imageUrl: absUrl,
            message: `I want to use this ${_originLabel(asset.origin).toLowerCase()} image as a reference.`,
        });
    }
}

function subscribeRecentAssetEvents() {
    // EventSource auto-reconnects — we only need to set it up once.
    if (window._recentAssetSSE) return;
    try {
        const url = '/api/events/stream?kinds=' + encodeURIComponent([
            'guild.asset.uploaded', 'gimp.asset.uploaded',
            'darktable.asset.uploaded', 'resolve.asset.uploaded',
        ].join(','));
        const es = new EventSource(url);
        window._recentAssetSSE = es;
        const handler = (ev) => {
            // Pulse the originating interface's chip so the user sees
            // which app just delivered an asset. The event type name
            // ("gimp.asset.uploaded") maps 1:1 to the chip key.
            try {
                const origin = (ev.type || '').split('.')[0];
                if (origin) markIfaceEngaged(origin);
            } catch (_) {/* no-op */}
            // Refresh and briefly flash the newly-landed thumb
            refreshRecentAssets().then(() => {
                try {
                    const data = JSON.parse(ev.data || '{}');
                    const hash = data.data && data.data.hash;
                    if (hash) _flashRecentAsset(hash);
                } catch (_) {/* no-op */}
            });
        };
        es.addEventListener('guild.asset.uploaded', handler);
        es.addEventListener('gimp.asset.uploaded', handler);
        es.addEventListener('darktable.asset.uploaded', handler);
        es.addEventListener('resolve.asset.uploaded', handler);
        es.addEventListener('error', () => {
            // EventSource will auto-retry; nothing to do
        });
    } catch (e) {
        // SSE unsupported — fall through to polling only
    }
}

function _flashRecentAsset(hash) {
    const el = document.querySelector(
        `.recent-asset-thumb[data-hash="${hash}"]`);
    if (!el) return;
    el.classList.remove('recent-asset-flash');
    // Force reflow so the animation restarts
    void el.offsetWidth;
    el.classList.add('recent-asset-flash');
}

function addTypingIndicator() {
    const div = document.createElement('div');
    div.className = 'message ai-message';
    div.id = 'typing-indicator';
    const char = characters.find(c => c.id === activeCharacterId);
    const avatarStyle = char && char.avatar_url
        ? `background-image: url(${char.avatar_url})`
        : `background: linear-gradient(135deg, #888, #aaa)`;
    div.innerHTML = `
        <div class="avatar-small" style="${avatarStyle}"></div>
        <div class="bubble typing-bubble">
            <span class="typing-dots"><span>.</span><span>.</span><span>.</span></span>
        </div>`;
    chatStream.appendChild(div);
    chatStream.scrollTop = chatStream.scrollHeight;
    _typingIndicatorMagic(div);
}

function removeTypingIndicator() {
    const el = document.getElementById('typing-indicator');
    if (el) el.remove();
}

// ═══════════════════════════════════════════════════════════════════════
//  LLM Mode Toggle (Local / Horde)
// ═══════════════════════════════════════════════════════════════════════
function setLlmMode(mode) {
    const localBtn = document.getElementById('llm-mode-local');
    const hordeBtn = document.getElementById('llm-mode-horde');
    const localSettings = document.getElementById('llm-local-settings');
    const hordeSettings = document.getElementById('llm-horde-settings');
    if (mode === 'horde') {
        localBtn.style.borderColor = '#333'; localBtn.style.color = '#888';
        hordeBtn.style.borderColor = '#ff4757'; hordeBtn.style.color = '#ff6b6b';
        localSettings.style.display = 'none';
        hordeSettings.style.display = 'block';
    } else {
        localBtn.style.borderColor = '#B246F2'; localBtn.style.color = '#eee';
        hordeBtn.style.borderColor = '#333'; hordeBtn.style.color = '#888';
        localSettings.style.display = 'block';
        hordeSettings.style.display = 'none';
    }
    // Store pending mode (applied on Save)
    localBtn.dataset.pendingMode = mode;
}

async function initialize() {
    // Fetch server config (launcher-configured defaults)
    try {
        const cfgRes = await fetch('/api/config');
        const cfg = await cfgRes.json();
        if(cfg.kobold_url) {
            koboldUrl = cfg.kobold_url;
        }
        if(cfg.comfyui_url) {
            comfyUrl = cfg.comfyui_url;
        }
        if(cfg.llm_mode) {
            llmMode = cfg.llm_mode;
        }
        if(cfg.sillytavern_url) {
            stUrl = cfg.sillytavern_url;
        }
        if(cfg.signal_bridge_url) {
            bridgeUrl = cfg.signal_bridge_url;
        }
        // Tag the body with .nsfw-build so the avatar dropdown unhides
        // the NSFW optgroup. SFW builds never see those entries.
        if (cfg.nsfw_mode) {
            document.body.classList.add('nsfw-build');
        } else {
            document.body.classList.remove('nsfw-build');
        }
        // Show persistent privacy banner when in horde mode
        _updatePrivacyBanner();
    } catch(e) {
        console.log('Could not fetch server config, using defaults');
    }
    koboldUrlInput.value = koboldUrl;
    comfyUrlInput.value = comfyUrl;
    stUrlInput.value = stUrl;
    bridgeUrlInput.value = bridgeUrl;

    // Check connections — ComfyUI polls faster so the VRAM/RAM/cache
    // meters feel live during generation.
    checkComfyConnection();
    checkSillyTavernConnection();
    checkSignalBridgeConnection();
    setInterval(checkComfyConnection, 5000);
    setInterval(checkSillyTavernConnection, 30000);
    setInterval(checkSignalBridgeConnection, 30000);
    // Active-interfaces widget — polls /api/interfaces and renders chips
    // for every frontend the registry reports as installed+enabled+online.
    // Dynamic: if no interface qualifies, the whole strip stays hidden.
    // Seed the per-app control matrix (the `target` host per app still
    // feeds the ⚡ Start button) before the first chip render so chip
    // state doesn't flash on first paint.
    refreshAppControlMatrix().then(refreshActiveInterfaces);
    setInterval(() => {
        refreshAppControlMatrix().then(refreshActiveInterfaces);
    }, 10000);
    // Exit button — POSTs /api/guild/exit. Connected apps keep running:
    // the user starts them explicitly via the ⚡ chip button, so a Guild
    // quit no longer tears down ComfyUI/Ollama/Kobold behind their back.
    const _exitBtn = document.getElementById('guild-exit-btn');
    if (_exitBtn) {
        _exitBtn.addEventListener('click', async () => {
            if (!confirm('Close the Wizard Guild? Connected apps keep running.')) return;
            _exitBtn.disabled = true;
            _exitBtn.textContent = '⏻ Exiting…';
            try {
                await fetch('/api/guild/exit', {method: 'POST'});
            } catch (e) { /* expected: socket dies mid-reply */ }
            document.body.style.filter = 'grayscale(1) brightness(0.7)';
            document.body.style.pointerEvents = 'none';
        });
    }

    // ── Preset cycle + character-hover preview helpers ────────────────
    // Declared as inner helpers because they close over nothing except
    // DOM; top-level so the init block above can call them on boot.
    function _wireGlobalPresetBtn() {
        const btn = document.getElementById('global-preset-btn');
        if (!btn) return;
        const PRESETS = [
            { key: 'turbo',    label: '⚡ Turbo',    cls: '' },
            { key: 'standard', label: '⚖️ Standard', cls: 'preset-standard' },
            { key: 'quality',  label: '💎 Quality',  cls: 'preset-quality' },
        ];
        // Prefer the server-side mirror of user_settings over
        // localStorage so the preset survives browser clears + syncs
        // across devices. Fall back to localStorage while the fetch is
        // in flight so the UI doesn't flicker back to the default.
        const savedLocal = localStorage.getItem('guild_preset') || 'turbo';
        let idx = Math.max(0,
            PRESETS.findIndex(p => p.key === savedLocal));
        if (idx < 0) idx = 0;
        const apply = (persist = true) => {
            const p = PRESETS[idx];
            btn.textContent = p.label;
            btn.classList.remove('preset-standard', 'preset-quality');
            if (p.cls) btn.classList.add(p.cls);
            window.generationPreset = p.key;
            try { localStorage.setItem('guild_preset', p.key); } catch (e) {}
            // Single write covers both concerns: POST
            // /api/video/quality-mode sets runtime state AND persists
            // to guild_config.user_settings.guild_preset server-side
            // (consolidated in the audit-tier cleanup). No separate
            // /api/user_settings round-trip required.
            if (persist) {
                fetch('/api/video/quality-mode', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({mode: p.key}),
                }).catch(() => {});
            }
            window.dispatchEvent(new CustomEvent('guildpresetchange',
                { detail: { preset: p.key } }));
        };
        apply(false);  // first render should not re-persist the same
                       // value we just loaded from localStorage.
        btn.addEventListener('click', () => {
            idx = (idx + 1) % PRESETS.length;
            apply();
        });
        // Pull the server's saved value once. If it's newer / different
        // from localStorage, adopt it — guild_config.json is the source
        // of truth across browsers and devices.
        fetch('/api/user_settings').then(r => r.ok ? r.json() : null)
            .then(d => {
                if (!d || !d.user_settings) return;
                const srv = d.user_settings.guild_preset;
                if (!srv) return;
                const srvIdx = PRESETS.findIndex(p => p.key === srv);
                if (srvIdx >= 0 && srvIdx !== idx) {
                    idx = srvIdx;
                    apply(false);
                }
            })
            .catch(() => {});
        // Also sync the current preset to the server's in-memory video
        // quality state on page load, so the freshly-restarted Guild
        // (which defaults to "turbo") matches whatever the user had
        // picked before. Fire-and-forget.
        fetch('/api/video/quality-mode', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({mode: PRESETS[idx].key}),
        }).catch(() => {});
    }

    // Persist any user setting to guild_config.user_settings. Silent on
    // failure — the localStorage fallback still carries the value for
    // the current browser. Used by _wireGlobalPresetBtn but exposed
    // broadly so other modules (LLM mode toggle, future pickers) can
    // mirror their choices the same way.
    function _persistUserSetting(key, value) {
        try {
            fetch('/api/user_settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key, value }),
            }).catch(() => {});
        } catch (e) {}
    }
    window._persistUserSetting = _persistUserSetting;

    function _wireLlmPicker() {
        const picker = document.getElementById('llm-picker');
        if (!picker) return;
        const pills = picker.querySelectorAll('.llm-pill');

        // Map the user-settings key "preferred_llm" values:
        //   "comfyui"   — reroute, no service start
        //   "ollama"    — ensure the local Ollama service is running
        //   "kobold_rp" — ensure the kobold_rp service is running
        // ComfyUI's embedded LLM is always available when ComfyUI is
        // online; no dedicated start call is needed.
        const NEEDS_START = { ollama: 'ollama', kobold_rp: 'kobold_rp' };

        const setActive = (key) => {
            pills.forEach(p => {
                p.classList.toggle('is-active',
                                     p.dataset.llm === key);
            });
        };

        // Initial render from /api/llm_status (carries both the live
        // backend + the stored `preferred`).
        fetch('/api/llm_status', { cache: 'no-store' })
            .then(r => r.ok ? r.json() : null)
            .then(s => {
                if (!s) return;
                // preferred_llm is the authoritative pick; fall back to
                // the live `backend` when nothing is persisted yet so
                // the pill already reflects reality on first render.
                const p = (s.preferred === 'kobold') ? 'kobold_rp'
                                                      : s.preferred;
                const live = (s.backend === 'kobold') ? 'kobold_rp'
                                                       : s.backend;
                setActive(p || live || 'comfyui');
            })
            .catch(() => setActive('comfyui'));

        pills.forEach(pill => {
            pill.addEventListener('click', async () => {
                const key = pill.dataset.llm;
                pills.forEach(p => p.classList.add('is-pending'));
                try {
                    // 1. Persist the choice server-side. guild_llm.chat
                    //    rotates on the next call so no restart needed.
                    await fetch('/api/user_settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            key: 'preferred_llm', value: key,
                        }),
                    });
                    // 2. Start the backend service if this pill demands
                    //    one (ComfyUI is a pure reroute → no start).
                    const svc = NEEDS_START[key];
                    if (svc) {
                        try {
                            await fetch('/api/app_control/start', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ app: svc }),
                            });
                        } catch (e) { /* silent — start is best-effort,
                                         the chain will still route */ }
                    }
                    setActive(key);
                } finally {
                    pills.forEach(p => p.classList.remove('is-pending'));
                }
            });
        });
    }

    function _wireWalkieTalkieBtn() {
        const btn = document.getElementById('walkie-btn');
        const input = document.getElementById('chat-input');
        if (!btn || !input) return;
        let recorder = null;
        let chunks = [];
        let active = false;
        const supportsMic = !!(navigator.mediaDevices &&
                                navigator.mediaDevices.getUserMedia &&
                                window.MediaRecorder);
        if (!supportsMic) {
            btn.disabled = true;
            btn.title = 'Browser does not support MediaRecorder / mic access.';
            return;
        }

        const start = async (ev) => {
            ev.preventDefault();
            if (active) return;
            active = true;
            btn.classList.add('walkie-recording');
            btn.textContent = '🔴';
            try {
                const stream = await navigator.mediaDevices.getUserMedia(
                    { audio: true });
                chunks = [];
                const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
                    ? 'audio/webm;codecs=opus' : 'audio/webm';
                recorder = new MediaRecorder(stream, { mimeType: mime });
                recorder.addEventListener('dataavailable', e => {
                    if (e.data && e.data.size > 0) chunks.push(e.data);
                });
                recorder.addEventListener('stop', async () => {
                    stream.getTracks().forEach(t => t.stop());
                    const blob = new Blob(chunks, { type: mime });
                    // Reset the UI even if the upload fails so the
                    // user can try again; we'll reopen the error below
                    // via a toast-style title update.
                    btn.classList.remove('walkie-recording');
                    btn.textContent = '⏳';
                    const reader = new FileReader();
                    reader.onloadend = async () => {
                        const b64 = String(reader.result || '')
                            .replace(/^data:[^,]+,/, '');
                        try {
                            const r = await fetch('/api/stt', {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                body: JSON.stringify({
                                    audio_b64: b64, mime,
                                }),
                            });
                            const d = await r.json();
                            if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
                            const text = (d.text || '').trim();
                            if (text) {
                                // Append to existing input — never clobber
                                // half-typed content the user left there.
                                input.value = (input.value
                                    ? input.value.trimEnd() + ' '
                                    : '') + text;
                                input.dispatchEvent(new Event('input'));
                                input.focus();
                            } else {
                                btn.title = 'STT returned empty text.';
                            }
                        } catch (err) {
                            btn.title = `STT failed: ${err.message || err}`;
                        } finally {
                            btn.textContent = '🎙️';
                        }
                    };
                    reader.readAsDataURL(blob);
                });
                recorder.start();
            } catch (err) {
                btn.classList.remove('walkie-recording');
                btn.textContent = '🎙️';
                btn.title = `Mic access denied: ${err.message || err}`;
                active = false;
            }
        };
        const stop = (ev) => {
            if (ev) ev.preventDefault();
            if (!active) return;
            active = false;
            if (recorder && recorder.state === 'recording') {
                try { recorder.stop(); } catch (e) {}
            }
        };
        // Pointer events cover mouse + touch uniformly.
        btn.addEventListener('pointerdown', start);
        btn.addEventListener('pointerup', stop);
        btn.addEventListener('pointercancel', stop);
        btn.addEventListener('pointerleave', stop);
    }

    function _installCharacterHoverPreview() {
        // Single reusable overlay element — swapping src is cheaper than
        // creating/destroying per hover. Positioned via mouse coords on
        // mouseenter + mousemove; removed from view on mouseleave.
        const preview = document.createElement('div');
        preview.className = 'character-hover-preview';
        preview.innerHTML = '<img alt="">';
        document.body.appendChild(preview);
        const img = preview.querySelector('img');

        const show = (avatarEl) => {
            const src = avatarEl.currentSrc || avatarEl.src
                       || avatarEl.style.backgroundImage
                              .replace(/^url\(["']?/, '')
                              .replace(/["']?\)$/, '');
            if (!src) return;
            img.src = src;
            preview.classList.add('visible');
        };
        const hide = () => preview.classList.remove('visible');
        const position = (x, y) => {
            // Pin the circle just to the right of the cursor. Clamp to
            // viewport so it never scrolls the page or hides off-screen.
            const w = preview.offsetWidth || 220;
            const h = preview.offsetHeight || 220;
            let left = x + 16;
            let top  = y - h / 2;
            if (left + w > window.innerWidth - 8)
                left = x - w - 16;
            if (top < 8) top = 8;
            if (top + h > window.innerHeight - 8)
                top = window.innerHeight - h - 8;
            preview.style.left = `${left}px`;
            preview.style.top  = `${top}px`;
        };

        // Delegate listener on #chat-stream so dynamically-added
        // character avatars pick up the behavior without re-wiring.
        const stream = document.getElementById('chat-stream');
        if (!stream) return;
        stream.addEventListener('mouseenter', (ev) => {
            const t = ev.target;
            if (!t || !t.classList) return;
            // Chat avatars are <img class="message-avatar"> or similar;
            // also match any .character-avatar the renderer may use.
            if (t.matches && (t.matches('img.message-avatar') ||
                               t.matches('.character-avatar') ||
                               t.matches('.avatar'))) {
                position(ev.clientX, ev.clientY);
                show(t);
            }
        }, true);
        stream.addEventListener('mousemove', (ev) => {
            if (!preview.classList.contains('visible')) return;
            position(ev.clientX, ev.clientY);
        });
        stream.addEventListener('mouseleave', (ev) => {
            const related = ev.relatedTarget;
            if (!related || !related.closest
                    || !related.closest('.character-hover-preview')) {
                hide();
            }
        }, true);
    }
    // Global generation preset cycling button. Persists to
    // localStorage (guild_preset) + publishes to window.generationPreset
    // so every generation action (wizards, spellcaster_actions, direct
    // cast) can read the current preset without threading it through
    // props. Order cycles: turbo → standard → quality → turbo.
    _wireGlobalPresetBtn();

    // Walkie-talkie STT: press-and-hold the 🎙️ button → record audio
    // → release → POST /api/stt with base64 audio → transcript lands
    // in the chat textarea. MediaRecorder + getUserMedia drive the
    // capture. Graceful degradation when the browser blocks mic, or
    // when no kobold_tts backend is registered (503 from the endpoint
    // prompts the user to right-click an antenna chip to register one).
    _wireWalkieTalkieBtn();

    // LLM primary-backend picker (3 pills in the sidebar header). Click
    // one to pin it as the first hop in guild_llm's chat chain and
    // spin up its service if it isn't running. Multiple backends can
    // stay online simultaneously (e.g. ComfyUI + a dedicated RP kobold
    // for SillyTavern); the pill just decides who answers first.
    _wireLlmPicker();

    // Character-hover circle preview — large circular portrait that
    // fades in near the cursor when the user mouses over an avatar in
    // the chat stream. See _installCharacterHoverPreview for details.
    _installCharacterHoverPreview();

    // Antennas strip — polls /api/antennas and renders one chip per
    // remote machine with declared / detected services. Gives the user
    // a live signal that a remote GPU pairing is alive (and how many
    // services it's reporting).
    refreshAntennas();
    setInterval(refreshAntennas, 10000);
    // Pair-new-antenna button — always visible in the Antennas header.
    // Opens a modal that exchanges a 6-digit tray code for the antenna's
    // bearer token (see openAntennaPairDialog above).
    const pairBtn = document.getElementById('pair-antenna-btn');
    if (pairBtn) pairBtn.addEventListener('click', openAntennaPairDialog);
    // Recent-assets strip — polls /api/assets and subscribes to
    // *.asset.uploaded on the event bus for live updates. Shows the
    // most recent N images from every connected interface.
    refreshRecentAssets();
    setInterval(refreshRecentAssets, 15000);
    subscribeRecentAssetEvents();

    // Check if video models available (for Animate All button)
    checkVideoModelAvailable();

    // Click any image to expand fullscreen
    _initLightboxDelegation();

    // Fetch System Prompt
    const promptRes = await fetch('/api/system_prompt');
    const promptData = await promptRes.json();
    systemPrompt = promptData.prompt;

    // Fetch Guild Members
    const charRes = await fetch('/api/characters');
    characters = await charRes.json();
    
    // Sync server-side pre-generated assets (from guild_launcher.py setup)
    await syncServerAssets();

    // Sync server-persisted wizard identities (survives browser clears)
    await syncServerIdentities();

    // Sync server-persisted LoRA toggles (survives browser clears)
    await syncServerLoraToggles();

    // Server ALWAYS wins for wizard names. Nuke any stale localStorage
    // names that differ from the server (LLM-generated scaffold overrides).
    // Only user-explicit renames (via rename dialog) survive.
    let savedIdentities = JSON.parse(localStorage.getItem('guild_identities') || '{}');
    characters.forEach(char => {
        if (savedIdentities[char.id]) {
            // Force server name — always — unless user explicitly renamed
            if (!savedIdentities[char.id]._user_renamed) {
                savedIdentities[char.id].name = char.name;
            } else {
                char.name = savedIdentities[char.id].name || char.name;
            }
            char.personality = savedIdentities[char.id].personality || char.personality;
            char.avatar_url = char.avatar_url || savedIdentities[char.id].avatar_url;
            char.animated_url = char.animated_url || savedIdentities[char.id].animated_url;
        }
    });
    localStorage.setItem('guild_identities', JSON.stringify(savedIdentities));

    applyGlobalBackground();
    renderSidebar();

    // Check LLM Connection & generate names
    await checkLlmAndGenerateNames();

    // First Time Global Generation (Avatars + Background)
    // Three paths:
    //   1. Server-driven setup is already running in a background thread
    //      (the launcher kicked it off via /api/setup/start). We enter
    //      "Archivist mode" — chat-lock UI, speech streaming, avatar
    //      arrivals piped into the chat as they happen.
    //   2. Setup is NOT running but some wizards are missing portraits
    //      (e.g. user closed the server mid-generation, or new wizards
    //      were added since the last run). Trigger a partial-setup pass
    //      that only generates the missing ones, then enter Archivist
    //      mode to stream their arrivals into the chat.
    //   3. Every wizard already has a portrait — nothing to do.
    let setupActive = await _maybeEnterArchivistMode();
    if (!setupActive) {
        const missing = (typeof characters !== 'undefined')
            ? characters.filter(c => !c.avatar_url) : [];
        if (missing.length > 0) {
            // Before triggering the avatar-gen background worker, confirm
            // ComfyUI is actually up. If it's down and a paired antenna
            // offers the comfyui service, prompt the user to start it
            // remotely instead of dropping into a stuck Archivist mode
            // that silently fails against an unreachable server.
            const readyForGen = await _ensureComfyUiOrOfferRemoteStart();
            if (readyForGen) {
                // Partial restart-recovery setup. The server's bg worker
                // honours skip_existing=True by default, so the call
                // only generates the ones we need.
                try {
                    await fetch('/api/setup/start', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ comfy_url: comfyUrl }),
                    });
                    await new Promise(r => setTimeout(r, 300));
                    setupActive = await _maybeEnterArchivistMode();
                } catch (e) {
                    console.warn('[Guild] could not start recovery setup:', e);
                }
            }
        }
    }
    if (!setupActive) {
        // No background setup running, no missing avatars — keep the
        // legacy fast-path for any edge case the server didn't pick up.
        await generateMissingAvatars();
    }
    // Final pass: paint placeholders + gate Animate All in case any
    // wizards landed in the sidebar with no avatar and no setup running.
    _refreshSidebarPlaceholders();

    // Select first by default
    if (characters.length > 0) {
        selectCharacter(characters[0].id);
    }
}

// ════════════════════════════════════════════════════════════════════
// Global image lightbox — click any image to expand fullscreen
// ════════════════════════════════════════════════════════════════════
//
// Click any <img> inside the chat, sidebar avatar, generated image,
// archivist portrait, or markdown inline image to open it in a
// fullscreen modal. Esc / click-outside / X to close.
//
// We use event delegation off document.body so it works for elements
// added dynamically (avatar arrivals, generated images in chat, etc.)
// without needing per-element wiring. Background-image div avatars
// (the sidebar character cards + active wizard header) are handled by
// reading their computed background-image URL when clicked.

let _lightboxEl = null;
let _lightboxImgEl = null;
let _lightboxEscHandler = null;

function _ensureLightbox() {
    if (_lightboxEl) return _lightboxEl;
    const el = document.createElement('div');
    el.id = 'image-lightbox';
    el.innerHTML = `
        <button class="lightbox-close" type="button" title="Close (Esc)" aria-label="Close">&times;</button>
        <img alt="" src=""/>
    `;
    document.body.appendChild(el);
    _lightboxEl = el;
    _lightboxImgEl = el.querySelector('img');
    // Click anywhere on the backdrop to close
    el.addEventListener('click', (ev) => {
        if (ev.target === el || ev.target.tagName === 'IMG') {
            // Image clicks pass through (they're inside the modal),
            // so we close on backdrop click only
            if (ev.target === el) closeLightbox();
        }
    });
    el.querySelector('.lightbox-close').addEventListener('click', closeLightbox);
    return el;
}

function openLightbox(src, alt) {
    if (!src) return;
    _ensureLightbox();
    _lightboxImgEl.src = src;
    _lightboxImgEl.alt = alt || '';
    _lightboxEl.classList.add('open');
    if (!_lightboxEscHandler) {
        _lightboxEscHandler = (e) => {
            if (e.key === 'Escape' && _lightboxEl && _lightboxEl.classList.contains('open')) {
                closeLightbox();
            }
        };
        document.addEventListener('keydown', _lightboxEscHandler);
    }
}

function closeLightbox() {
    if (!_lightboxEl) return;
    _lightboxEl.classList.remove('open');
    if (_lightboxEscHandler) {
        document.removeEventListener('keydown', _lightboxEscHandler);
        _lightboxEscHandler = null;
    }
}

function _extractCssBgUrl(el) {
    if (!el) return null;
    const bg = window.getComputedStyle(el).backgroundImage;
    if (!bg || bg === 'none') return null;
    const m = bg.match(/url\(["']?([^"')]+)["']?\)/);
    return m ? m[1] : null;
}

function _initLightboxDelegation() {
    document.body.addEventListener('click', (ev) => {
        // Skip if a tooltip/modal/lockdown intercepted the click
        if (ev.defaultPrevented) return;
        let el = ev.target;
        // Walk up a few levels in case the click hit a child of the avatar
        for (let i = 0; i < 4 && el && el !== document.body; i++) {
            if (el.tagName === 'IMG') {
                // Skip the lightbox itself + the wizard tooltip avatar
                if (el.closest('#image-lightbox')) return;
                openLightbox(el.src, el.alt);
                ev.preventDefault();
                return;
            }
            // Background-image avatar divs (sidebar cards, header avatar)
            if (el.classList && (
                el.classList.contains('avatar')
                || el.classList.contains('avatar-small')
            )) {
                const url = _extractCssBgUrl(el);
                if (url) {
                    openLightbox(url, el.getAttribute('aria-label') || '');
                    ev.preventDefault();
                    return;
                }
            }
            el = el.parentElement;
        }
    });
}

// ════════════════════════════════════════════════════════════════════
// The Archivist — synthetic setup-mode wizard persona
// ════════════════════════════════════════════════════════════════════
//
// During first-run / restart-recovery setup we inject a synthetic
// "studio_archivist" wizard into the local `characters` array. He
// appears at the top of the sidebar, gets auto-selected so the chat
// header reads "The Archivist", and every other wizard is dimmed by
// the lockdown CSS. When setup completes, the Archivist is removed
// from the sidebar and the user is auto-switched to the first real
// wizard (preferring Imaginus if she's installed). The Archivist is
// purely a frontend artifact — the backend never knows about him.

const ARCHIVIST_ID = "studio_archivist";

function _buildArchivistCharacter() {
    return {
        id: ARCHIVIST_ID,
        type: "studio",
        name: "The Archivist",
        subtext: "First-run guide — banishes himself when setup is done",
        color1: "hsl(45, 95%, 55%)",
        color2: "hsl(20, 95%, 50%)",
        archetype: "an ancient bespectacled wizard surrounded by floating scrolls and arcane diagrams",
        // Use the placeholder icon URL so we don't need a generated avatar
        avatar_url: _PLACEHOLDER_AVATAR_URL,
        personality: "Patient, professorial, slightly self-deprecating. Knows he'll be banished as soon as the real wizards arrive.",
        is_archivist: true,  // sentinel for css/js gates
    };
}

let _previousActiveCharacterId = null;

function _injectArchivistIntoSidebar() {
    if (typeof characters === 'undefined') return;
    if (characters.find(c => c.id === ARCHIVIST_ID)) return;
    const archivist = _buildArchivistCharacter();
    characters.unshift(archivist);
    _previousActiveCharacterId = activeCharacterId;
    if (typeof renderSidebar === 'function') {
        try { renderSidebar(); } catch (e) {}
    }
    // Auto-select the Archivist so the chat header shows his name
    if (typeof selectCharacter === 'function') {
        try { selectCharacter(ARCHIVIST_ID); } catch (e) {}
    }
}

function _banishArchivistFromSidebar() {
    if (typeof characters === 'undefined') return;
    const idx = characters.findIndex(c => c.id === ARCHIVIST_ID);
    if (idx === -1) return;
    characters.splice(idx, 1);
    if (typeof renderSidebar === 'function') {
        try { renderSidebar(); } catch (e) {}
    }
    // Switch the user to a real wizard. Prefer Imaginus if she's
    // installed, otherwise the first remaining character.
    let nextId = _previousActiveCharacterId;
    if (!nextId || nextId === ARCHIVIST_ID
        || !characters.find(c => c.id === nextId)) {
        const imaginus = characters.find(c => c.id === "studio_imaginus");
        nextId = imaginus ? imaginus.id
                          : (characters[0] && characters[0].id);
    }
    if (nextId && typeof selectCharacter === 'function') {
        try { selectCharacter(nextId); } catch (e) {}
    }
    _previousActiveCharacterId = null;
}

// ════════════════════════════════════════════════════════════════════
// Archivist mode — chat-locked first-run experience
// ════════════════════════════════════════════════════════════════════
//
// When the launcher kicks off background avatar generation, the frontend
// detects it on page load via /api/setup/status. We then:
//   1. Lock the chat input with a friendly explanation
//   2. Greet the user as "The Archivist" and read out a tour of the
//      app architecture from README sections (single source of truth)
//   3. Poll /api/setup/status every 2 s and render each new wizard
//      avatar into the chat as it lands
//   4. Drip the README speech sections in between avatar arrivals so
//      the wait is informative rather than empty
//   5. Unlock the chat once phase === 'complete'
//
// All of this runs in parallel so the user has something to read
// while the GPU renders 32 portraits.

const _ARCHIVIST_AVATAR_STYLE =
    "background: radial-gradient(circle at 30% 30%, #facc15, #b45309); "
    + "color: #1a1a2e; display: flex; align-items: center; "
    + "justify-content: center; font-weight: 700; font-size: 14px;";
const _ARCHIVIST_AVATAR_HTML = "📜";

function _addArchivistMessage(markdown) {
    // Render Archivist speech as a system-style bubble with the scroll
    // emoji. Markdown bold/italic gets rendered as HTML; everything
    // else stays as paragraphs.
    const html = _renderSimpleMarkdown(markdown);
    const msg = document.createElement('div');
    msg.className = 'message ai-message archivist-message';
    msg.innerHTML = `
        <div class="avatar-small archivist-avatar" style="${_ARCHIVIST_AVATAR_STYLE}">${_ARCHIVIST_AVATAR_HTML}</div>
        <div class="bubble archivist-bubble">${html}</div>
    `;
    chatStream.appendChild(msg);
    chatStream.scrollTop = chatStream.scrollHeight;
    if (typeof _messageEntrance === 'function') _messageEntrance(msg);
}

function _renderSimpleMarkdown(md) {
    // Tiny, safe-by-construction markdown renderer for the Archivist
    // speech blocks. Handles **bold**, *italic*, `code`, paragraph breaks,
    // simple ``` code blocks, [link](url), ![alt](url) images, and
    // unordered lists. We do basic HTML escaping first so user-
    // controlled content can't inject.
    if (!md) return '';
    const esc = (s) => s
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    let s = md.trim();
    // Pull out fenced code blocks first so other rules don't touch them
    const codeBlocks = [];
    s = s.replace(/```[a-z]*\n([\s\S]*?)```/gi, (_, body) => {
        codeBlocks.push(esc(body));
        return `\u0000CODE${codeBlocks.length - 1}\u0000`;
    });
    // Pull out images BEFORE escaping so the markup survives.
    // Format: ![alt text](url)
    // Accepts:
    //   - http(s) absolute URLs
    //   - server-rooted paths (/asset_image/foo.png — legacy)
    //   - repo-relative paths (assets/foo.png, tavern/characters/foo.png)
    // The repo-relative form is what GitHub renders natively, so the
    // README is the single source of truth. We rewrite those paths to
    // the matching server route so the in-Guild markdown renderer can
    // serve them through tavern/server.py's image endpoints.
    const images = [];
    const _rewriteImageUrl = (url) => {
        if (/^https?:\/\//i.test(url)) return url;
        if (url.startsWith('/')) return url;
        // Strip "./" if present
        const clean = url.replace(/^\.\//, '');
        if (clean.startsWith('assets/')) {
            return '/asset_image/' + clean.substring('assets/'.length);
        }
        if (clean.startsWith('tavern/characters/')) {
            return '/character_image/' + clean.substring('tavern/characters/'.length);
        }
        // Unknown relative path — pass through and let the browser try
        return url;
    };
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, url) => {
        const safeAlt = esc(alt);
        const safeUrl = esc(_rewriteImageUrl(url));
        images.push(`<img class="archivist-inline-img" src="${safeUrl}" alt="${safeAlt}" loading="lazy">`);
        return `\u0000IMG${images.length - 1}\u0000`;
    });
    s = esc(s);
    // Bold, italic, inline code, links
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
    s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    s = s.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g,
                  '<a href="$2" target="_blank" rel="noopener">$1</a>');
    // Numbered + bullet lists
    const lines = s.split('\n');
    let out = [];
    let inList = null;  // 'ul' | 'ol' | null
    let para = [];
    const flushPara = () => {
        if (para.length) {
            out.push('<p>' + para.join(' ') + '</p>');
            para = [];
        }
    };
    const closeList = () => {
        if (inList) {
            out.push(`</${inList}>`);
            inList = null;
        }
    };
    for (const raw of lines) {
        const line = raw;
        if (/^\s*$/.test(line)) {
            flushPara();
            closeList();
            continue;
        }
        const ulMatch = line.match(/^\s*[-*]\s+(.*)$/);
        const olMatch = line.match(/^\s*\d+\.\s+(.*)$/);
        if (ulMatch) {
            flushPara();
            if (inList !== 'ul') { closeList(); out.push('<ul>'); inList = 'ul'; }
            out.push(`<li>${ulMatch[1]}</li>`);
            continue;
        }
        if (olMatch) {
            flushPara();
            if (inList !== 'ol') { closeList(); out.push('<ol>'); inList = 'ol'; }
            out.push(`<li>${olMatch[1]}</li>`);
            continue;
        }
        closeList();
        para.push(line);
    }
    flushPara();
    closeList();
    let html = out.join('');
    html = html.replace(/\u0000CODE(\d+)\u0000/g, (_, i) => `<pre><code>${codeBlocks[+i]}</code></pre>`);
    html = html.replace(/\u0000IMG(\d+)\u0000/g, (_, i) => images[+i] || '');
    return html;
}

let _archivistLocked = false;
let _archivistRenderedAvatarIds = new Set();
let _archivistSpokenSections = new Set();
let _archivistSpeechSections = null;
let _archivistSpeechOrder = [];
let _archivistPollTimer = null;
let _archivistRenderedNarrationCount = 0;

function _lockChatForArchivist() {
    _archivistLocked = true;
    if (chatInput) {
        chatInput.disabled = true;
        chatInput.placeholder = "The Archivist is finishing setup… one moment.";
    }
    if (sendBtn) sendBtn.disabled = true;
    // Lockdown class on <body> so CSS can dim every wizard card and
    // disable every header/sidebar button except #settings-btn.
    document.body.classList.add('archivist-lockdown');
    // Inject the synthetic Archivist persona so the chat header reads
    // "The Archivist" instead of whichever wizard happened to be active.
    _injectArchivistIntoSidebar();
}

function _unlockChatAfterArchivist() {
    if (!_archivistLocked) return;
    _archivistLocked = false;
    if (chatInput) {
        chatInput.disabled = false;
        chatInput.placeholder = "Speak to the wizard…";
    }
    if (sendBtn) sendBtn.disabled = false;
    document.body.classList.remove('archivist-lockdown');
    // Banish the Archivist from the sidebar and switch the user to a
    // real wizard now that setup is complete.
    _banishArchivistFromSidebar();
}

function _renderNewNarration(snapshot) {
    // Stream any backend narration entries that we haven't rendered yet.
    // Each entry has {ts, kind, text}. Kind controls the bubble style:
    //   heading  — main archivist bubble (markdown)
    //   progress — small italic line ("Summoning Imaginus 1/32")
    //   detail   — secondary info bubble
    //   question — interactive (future use — F10)
    //   error    — red-tinted error bubble
    //   done     — green-tinted closing line
    const narration = snapshot.narration || [];
    if (narration.length <= _archivistRenderedNarrationCount) return;
    for (let i = _archivistRenderedNarrationCount; i < narration.length; i++) {
        const entry = narration[i];
        if (!entry || !entry.text) continue;
        const text = entry.text;
        const kind = entry.kind || 'detail';
        if (kind === 'heading' || kind === 'done') {
            _addArchivistMessage(text);
        } else if (kind === 'error') {
            const msg = document.createElement('div');
            msg.className = 'message ai-message archivist-message archivist-error';
            msg.innerHTML = `
                <div class="avatar-small archivist-avatar" style="${_ARCHIVIST_AVATAR_STYLE}">${_ARCHIVIST_AVATAR_HTML}</div>
                <div class="bubble archivist-bubble" style="border-color: rgba(255, 71, 87, 0.45);">
                    <p>${_renderSimpleMarkdown(text)}</p>
                </div>`;
            chatStream.appendChild(msg);
            chatStream.scrollTop = chatStream.scrollHeight;
            if (typeof _messageEntrance === 'function') _messageEntrance(msg);
        } else if (kind === 'progress') {
            // Inline progress lines — small italic, no bubble chrome
            const msg = document.createElement('div');
            msg.className = 'archivist-progress-line';
            msg.innerHTML = _renderSimpleMarkdown(text);
            chatStream.appendChild(msg);
            chatStream.scrollTop = chatStream.scrollHeight;
        } else {
            // detail / question / unknown — small archivist bubble
            _addArchivistMessage(text);
        }
    }
    _archivistRenderedNarrationCount = narration.length;
}

async function _fetchArchivistSpeech() {
    try {
        const res = await fetch('/api/setup/speech');
        const data = await res.json();
        _archivistSpeechSections = data.sections || {};
        _archivistSpeechOrder = data.order || Object.keys(_archivistSpeechSections);
    } catch (e) {
        console.warn('[Archivist] could not fetch speech sections', e);
        _archivistSpeechSections = {};
        _archivistSpeechOrder = [];
    }
}

function _speakNextSection() {
    // Walk the speech section order and emit the next un-spoken one.
    // Returns true if a section was emitted, false if we've recited all.
    for (const name of _archivistSpeechOrder) {
        if (_archivistSpokenSections.has(name)) continue;
        if (name === 'ready') continue;  // 'ready' is reserved for the end
        const body = _archivistSpeechSections[name];
        if (!body) continue;
        _archivistSpokenSections.add(name);
        _addArchivistMessage(body);
        return true;
    }
    return false;
}

function _renderNewAvatars(snapshot) {
    // Walk the snapshot's avatar list and add a chat message for each
    // one we haven't rendered yet. Also updates the live wizard list
    // so the sidebar avatar appears.
    const arrivals = snapshot.avatars || [];
    let newCount = 0;
    for (const av of arrivals) {
        if (_archivistRenderedAvatarIds.has(av.id)) continue;
        _archivistRenderedAvatarIds.add(av.id);
        newCount++;
        // Update in-memory character list
        const char = (typeof characters !== 'undefined')
            ? characters.find(c => c.id === av.id) : null;
        if (char) {
            char.avatar_url = av.avatar_url;
            char.name = char.name || av.name;
        }
        // Render the avatar arrival as a tall portrait card with
        // sparkle particles + a brief shake on the portrait. The
        // sparkles are CSS-driven (no brightness flicker), the shake
        // is a 0.9 s one-shot transform translate keyframe.
        const msg = document.createElement('div');
        msg.className = 'message ai-message archivist-arrival';
        // av.name / av.avatar_url come from Guild event-bus payloads
        // (an attacker with publish access controls them). Escape + clamp.
        const _avName = _esc(av.name);
        const _avSrc = _esc(_safeSrc(av.avatar_url));
        msg.innerHTML = `
            <div class="avatar-small archivist-avatar" style="${_ARCHIVIST_AVATAR_STYLE}">${_ARCHIVIST_AVATAR_HTML}</div>
            <div class="bubble archivist-bubble">
                <span class="archivist-sparkle"></span>
                <span class="archivist-sparkle"></span>
                <span class="archivist-sparkle"></span>
                <span class="archivist-sparkle"></span>
                <span class="archivist-sparkle"></span>
                <span class="archivist-sparkle"></span>
                <p><strong>${_avName}</strong> has arrived.</p>
                <img src="${_avSrc}" alt="${_avName}" class="archivist-portrait"/>
            </div>
        `;
        chatStream.appendChild(msg);
        chatStream.scrollTop = chatStream.scrollHeight;
        if (typeof _messageEntrance === 'function') _messageEntrance(msg);
    }
    return newCount;
}

async function _archivistPollOnce() {
    let snapshot;
    try {
        const res = await fetch('/api/setup/status');
        snapshot = await res.json();
    } catch (e) {
        return;  // transient, retry next poll
    }
    // Render any new backend narration entries first — these are the
    // verbose substage messages (detecting, painting tavern, summoning
    // Imaginus 5/32, etc.) and they should appear in chronological
    // order with the avatar arrivals interleaved.
    _renderNewNarration(snapshot);

    const newCount = _renderNewAvatars(snapshot);
    // Update the per-wizard pending state map so the sidebar shows
    // the right animation: 'active' for whichever wizard ComfyUI is
    // currently rendering, 'queued' for everyone still waiting.
    _avatarPendingState = {};
    const pendingIds = snapshot.pending_ids || [];
    const activeId = snapshot.current_id;
    for (const cid of pendingIds) {
        _avatarPendingState[cid] = (cid === activeId) ? 'active' : 'queued';
    }
    if (activeId && !_avatarPendingState[activeId]) {
        _avatarPendingState[activeId] = 'active';
    }
    // Repaint the sidebar placeholders so the queued/active animations
    // follow the live snapshot, then re-gate the Animate All button.
    _refreshSidebarPlaceholders();

    // README speech sections now drip in only AFTER all backend narration
    // is caught up — they're complementary tour content rather than the
    // primary status feed.
    if (newCount === 0 && snapshot.narration && snapshot.narration.length === _archivistRenderedNarrationCount) {
        _speakNextSection();
    }
    // Apply the live tavern background as soon as setup finishes painting it
    if (snapshot.background_url) {
        try {
            localStorage.setItem('guild_global_bg', snapshot.background_url);
            if (typeof applyGlobalBackground === 'function') applyGlobalBackground();
        } catch (e) {}
    }
    // Re-render sidebar so newly-arrived avatars show up there too
    if (newCount > 0 && typeof renderSidebar === 'function') {
        try { renderSidebar(); } catch (e) {}
    }
    if (snapshot.phase === 'complete') {
        // Recite any remaining sections, then the closing 'ready' block
        while (_speakNextSection()) { /* drain */ }
        const ready = (_archivistSpeechSections || {}).ready;
        if (ready && !_archivistSpokenSections.has('ready')) {
            _archivistSpokenSections.add('ready');
            _addArchivistMessage(ready);
        }
        _unlockChatAfterArchivist();
        if (_archivistPollTimer) {
            clearInterval(_archivistPollTimer);
            _archivistPollTimer = null;
        }
        try {
            localStorage.setItem('guild_setup_complete', 'true');
        } catch (e) {}
    }
}

// Probe ComfyUI. If it's down, check whether a paired antenna can
// start it remotely and offer the user a one-click Start. Returns true
// when the caller should proceed with avatar generation, false when it
// should abort (ComfyUI still unreachable and the user declined).
async function _ensureComfyUiOrOfferRemoteStart() {
    let status;
    try {
        const res = await fetch('/api/setup/comfyui-status');
        status = await res.json();
    } catch (e) {
        // Probe itself failed — let the legacy fallback run so behavior
        // doesn't regress for users on older server builds without this
        // endpoint.
        return true;
    }
    if (status.reachable) return true;
    const antenna = status.antenna;
    if (!antenna || !antenna.can_start) {
        // No remote option available. Show a non-blocking banner so the
        // user knows why the sidebar wizards stay empty, but don't kick
        // off the avatar worker against a server that won't respond.
        _showComfyDownBanner(status);
        return false;
    }
    // Remote start is possible — ask the user.
    const userWantsStart = await _askStartRemoteComfy(antenna);
    if (!userWantsStart) {
        _showComfyDownBanner(status);
        return false;
    }
    // Fire the antenna service start + poll for reachability.
    const started = await _startRemoteComfyAndWait(antenna);
    if (!started) {
        _showComfyDownBanner(status, { startFailed: true });
        return false;
    }
    return true;
}

function _askStartRemoteComfy(antenna) {
    // Lightweight inline modal — no new dependency, no new CSS class:
    // re-use the settings modal shell so the styling stays consistent.
    return new Promise((resolve) => {
        const wrap = document.createElement('div');
        wrap.className = 'modal-overlay';
        wrap.style.cssText =
            'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:10000;' +
            'display:flex;align-items:center;justify-content:center;';
        const host = antenna.hostname || antenna.agent_url || 'remote antenna';
        const body = document.createElement('div');
        body.style.cssText =
            'background:#1b1b1e;color:#eee;border:1px solid #444;border-radius:8px;' +
            'max-width:480px;padding:22px 26px;box-shadow:0 8px 40px rgba(0,0,0,0.5);' +
            'font-family:inherit;';
        body.innerHTML =
            '<h3 style="margin:0 0 10px 0;font-size:1.1em;">ComfyUI is not running</h3>' +
            '<p style="margin:0 0 14px 0;opacity:0.85;line-height:1.45;">' +
            'Your antenna <b>' + host + '</b> has ComfyUI installed but the ' +
            'service is down. Start it remotely to continue?' +
            '</p>' +
            '<div style="display:flex;gap:10px;justify-content:flex-end;">' +
            '<button data-act="no" style="padding:7px 14px;background:#333;color:#ccc;' +
            'border:1px solid #555;border-radius:4px;cursor:pointer;">Not now</button>' +
            '<button data-act="yes" style="padding:7px 14px;background:#5d4fa7;color:#fff;' +
            'border:1px solid #7a6ad0;border-radius:4px;cursor:pointer;">' +
            'Start ComfyUI on ' + host + '</button>' +
            '</div>';
        wrap.appendChild(body);
        document.body.appendChild(wrap);
        body.querySelector('[data-act="yes"]').onclick = () => {
            wrap.remove();
            resolve(true);
        };
        body.querySelector('[data-act="no"]').onclick = () => {
            wrap.remove();
            resolve(false);
        };
    });
}

async function _startRemoteComfyAndWait(antenna) {
    // Fire the antenna-side POST /service/start, then poll comfyui-status
    // until reachable or we hit the budget. 60s is enough for the WAN
    // box to cold-start ComfyUI on a reasonable machine; beyond that the
    // user is better off investigating the antenna logs directly.
    try {
        const res = await fetch('/api/antenna/service/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ service: 'comfyui' }),
        });
        if (!res.ok) {
            console.warn('[Guild] antenna start refused:', res.status);
        }
    } catch (e) {
        console.warn('[Guild] antenna start request failed:', e);
        return false;
    }
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 3000));
        try {
            const r = await fetch('/api/setup/comfyui-status');
            const s = await r.json();
            if (s.reachable) return true;
        } catch (e) {
            /* keep polling */
        }
    }
    return false;
}

function _showComfyDownBanner(status, opts) {
    opts = opts || {};
    // Idempotent — only one banner at a time.
    if (document.getElementById('comfy-down-banner')) return;
    const bar = document.createElement('div');
    bar.id = 'comfy-down-banner';
    bar.style.cssText =
        'position:fixed;top:0;left:0;right:0;z-index:9500;padding:10px 18px;' +
        'background:#3a2020;color:#ffd7d7;font-size:0.92em;text-align:center;' +
        'border-bottom:1px solid #5a3030;';
    const url = (status && status.comfyui_url) || '';
    let msg = 'ComfyUI is unreachable at ' + url + '.';
    if (opts.startFailed) {
        msg += ' Remote start did not complete within 60s — check the ' +
               'antenna logs.';
    } else if (status && status.antenna && status.antenna.can_start) {
        msg += ' Paired antenna can start it remotely — reopen to retry.';
    } else {
        msg += ' Start ComfyUI or pair an antenna that provides it.';
    }
    bar.textContent = msg + '  ';
    const close = document.createElement('button');
    close.textContent = 'dismiss';
    close.style.cssText =
        'margin-left:10px;background:transparent;color:#ffd7d7;border:1px solid #7a4040;' +
        'border-radius:3px;padding:2px 8px;cursor:pointer;font-size:0.85em;';
    close.onclick = () => bar.remove();
    bar.appendChild(close);
    document.body.appendChild(bar);
}

async function _maybeEnterArchivistMode() {
    // Returns true if we entered Archivist mode (background setup is
    // running on the server), false otherwise.
    let snapshot;
    try {
        const res = await fetch('/api/setup/status');
        snapshot = await res.json();
    } catch (e) {
        return false;
    }
    // Don't enter Archivist mode if setup is already complete or never started
    if (snapshot.phase === 'idle' || snapshot.phase === 'complete') {
        return false;
    }
    // We're in the middle of background avatar generation — take over
    _lockChatForArchivist();
    await _fetchArchivistSpeech();
    // Recite the welcome immediately so the user sees something
    const welcome = (_archivistSpeechSections || {}).welcome;
    if (welcome) {
        _archivistSpokenSections.add('welcome');
        _addArchivistMessage(welcome);
    }
    // Render any avatars that already finished before the page loaded
    _renderNewAvatars(snapshot);
    // Drip the next section right away so there's content before the
    // first avatar lands
    _speakNextSection();
    // Start polling — every 2 seconds is plenty
    _archivistPollTimer = setInterval(_archivistPollOnce, 2000);
    return true;
}

async function checkLlmAndGenerateNames() {
    try {
        if (llmMode === 'horde') {
            // Horde is always "connected" — it's a cloud service
            llmDot.className = "dot yellow";
            llmStatus.textContent = "LLM: AI Horde";
            llmStatus.title = "\u26a0 ZERO PRIVACY — All text sent to volunteer workers";
            await generateNamesForCharacters();
        } else {
            if (await probeLlm(koboldUrl)) {
                llmDot.className = "dot green";
                llmStatus.textContent = "LLM: Connected";
                // Transport probe passing (e.g. Ollama /api/tags) doesn't
                // mean the Guild's guild_llm.chat() chain can actually
                // serve: ComfyUI-native LLM may be unreachable and each
                // llm_generate then pays the full backend-exhaustion cost
                // (~8s+) before returning 502. With ~35 wizards × 2 calls
                // that's a 10+ min boot hang behind the splash. Ask the
                // Guild directly if the composite chain is healthy before
                // entering the per-wizard naming loop.
                if (await _guildLlmHealthy()) {
                    await generateNamesForCharacters();
                }
            } else { throw new Error("Bad response"); }
        }
    } catch(e) {
        llmDot.className = "dot red";
        llmStatus.textContent = "LLM: Disconnected";
    }
    // Kick off the recurring status poll once chat/probe landed.
    // The poll surfaces live backend transitions (Local:Ollama →
    // Theo:ComfyUI → "Reloading…") that the one-shot probe can't see.
    _startLlmStatusPoll();
}

// ─────────────────────────────────────────────────────────────────────
//  Live LLM status poll — drives the sidebar indicator in real time.
//  Server updates spellcaster_core.guild_llm._STATUS on every chat()
//  call. We poll every 3s; the indicator flips green/blue/red based on
//  the reported state. "busy" and "reloading" both pulse blue so the
//  user gets immediate feedback when a prompt-enhance cycle fires.
// ─────────────────────────────────────────────────────────────────────
let _llmStatusTimer = null;
let _llmStatusLastBusyAt = 0;
function _startLlmStatusPoll() {
    if (_llmStatusTimer) return;
    _llmStatusTimer = setInterval(_pollLlmStatusOnce, 3000);
    _pollLlmStatusOnce();
}
async function _pollLlmStatusOnce() {
    try {
        const r = await fetch('/api/llm_status', { cache: 'no-store' });
        if (!r.ok) return;
        const s = await r.json();
        if (llmMode === 'horde') return; // Horde label wins
        const backend = s.backend;
        const host = s.host;
        const state = s.state || 'idle';
        // Map state → dot color + label. Blue pulse for busy so the
        // user sees "something is happening" without needing a spinner.
        if (state === 'busy') {
            llmDot.className = 'dot blue pulse';
            llmStatus.textContent = `LLM: ${host || '?'}:${_prettyBackend(backend)} · working`;
            _llmStatusLastBusyAt = Date.now();
        } else if (state === 'reloading' || state === 'unloaded') {
            llmDot.className = 'dot blue pulse';
            llmStatus.textContent = `LLM: ${host || '?'}:${_prettyBackend(backend)} · ${state}`;
        } else if (state === 'error') {
            llmDot.className = 'dot red';
            llmStatus.textContent = `LLM: ${host || '?'}:${_prettyBackend(backend)} · error`;
            llmStatus.title = s.last_error || '';
        } else if (backend) {
            // idle with a known last-used backend → connected
            llmDot.className = 'dot green';
            llmStatus.textContent = `LLM: ${host || '?'}:${_prettyBackend(backend)}`;
            llmStatus.title = s.model ? `model: ${s.model}` : '';
        }
        // state == 'idle' with no backend means "never used yet" — leave
        // whatever checkLlmAndGenerateNames put there.

        // Mirror the last-used backend into _managedLive so the
        // synthetic Ollama / Kobold / ComfyUI chips in the Connected
        // apps row turn green whenever that backend actually served a
        // request. busy/reloading/idle all count as "alive".
        if (backend && state !== 'error') {
            const ml = (window._managedLive = window._managedLive || {});
            ml[backend] = true;
        }
    } catch (e) { /* silent — indicator stays on last known state */ }
}
function _prettyBackend(b) {
    if (!b) return '?';
    const map = { ollama: 'Ollama', comfyui: 'ComfyUI', kobold: 'Kobold' };
    return map[b] || b;
}

// Detect when a character's `name` is still the raw ComfyUI model
// filename (e.g., "juggernautXL_v9Rundiffusionphoto2" or
// "sloppyMessyMix_sloppyMessyMixV1"). These look like filenames, not
// fantasy wizard names, and should go through the LLM rename step.
// We flag anything that:
//   - contains an underscore AND a digit (version markers v9, v170, v1_0),
//   - ends in a camelCase model suffix (vXX, fp8, Q6, safetensors),
//   - contains 3+ consecutive caps (XL, HD, AIO), OR
//   - already is the literal "Unnamed Wizard" sentinel.
function _looksLikeRawModelFilename(name) {
    if (!name) return true;
    if (name === "Unnamed Wizard") return true;
    if (/[_\-][vV]\d+/.test(name)) return true;            // _v9, _V170
    if (/_\d/.test(name)) return true;                     // _1, _0
    if (/(fp8|fp16|q4|q6|q8|bf16|safetensors|gguf|aio|xl|hd|pony|noob)/i.test(name)) return true;
    if (/[A-Z]{3,}/.test(name)) return true;               // XL, HD, AIO
    if (name.length > 30) return true;                     // too long to be a fantasy name
    return false;
}

async function generateNamesForCharacters() {
    // If a character name is Unnamed Wizard OR a raw model filename,
    // prompt the LLM to rename it. Studio characters already have
    // proper names — skip them. Track names already assigned so
    // near-identical models don't collide.
    const takenNames = new Set(
        characters.filter(c => c.name && !_looksLikeRawModelFilename(c.name))
                  .map(c => c.name.toLowerCase())
    );
    for(let i=0; i<characters.length; i++) {
        let char = characters[i];
        if(char.type === "studio" && !char.personality) {
            // Generate a real personality for studio characters via LLM
            try {
                let pCtx = `Context: A magical wizard named ${char.name} is the Guild's specialist in ${char.subtext}. They live inside an enchanted ComfyUI interface.\nCommand: Write exactly one vivid, eccentric sentence describing their personality quirk and speaking style. Make them memorable and fun — maybe they're dramatic, obsessive about their craft, sarcastic, poetic, or hilariously intense. No generic descriptions.\nPersonality:`;
                const pData = await llmGenerate({ prompt: pCtx, max_length: 80, temperature: 0.9, stop_sequence: ["\n"] });
                let llmPers = pData.results[0].text.trim();
                char.personality = llmPers || `A dedicated and powerful expert in ${char.subtext}.`;
            } catch(e) {
                char.personality = `A dedicated and powerful expert in ${char.subtext}.`;
            }
            saveIdentity(char);
        }
        if(_looksLikeRawModelFilename(char.name)) {
            // First attempt — free-form generation
            let avoidList = takenNames.size > 0 ? `\nAvoid these names (already taken): ${Array.from(takenNames).slice(0, 20).join(", ")}.` : "";
            const modelHint = char.model_name
                ? `\nTheir primary model is called "${char.model_name}" (architecture: ${char.model_arch || 'unknown'}). Hint at what the model does.`
                : "";
            let context = `Context: We are naming magical avatars for a ComfyUI image-generation interface.\nCommand: Invent a single, very short, creative fantasy name (1-2 words, e.g. Zephyr, Duskweave, Pyralis) for a wizard specializing in: ${char.subtext}. Do NOT use titles like 'Master of'.${modelHint}${avoidList}\nName:`;
            try {
                const data = await llmGenerate({ prompt: context, max_length: 15, temperature: 0.8, stop_sequence: ["\n", "."] });
                let llmName = data.results[0].text.trim().replace(/["']/g, '');
                // Uniquify against taken names — append roman numeral if collision
                if (llmName && takenNames.has(llmName.toLowerCase())) {
                    const romans = ["II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];
                    for (const r of romans) {
                        const candidate = `${llmName} ${r}`;
                        if (!takenNames.has(candidate.toLowerCase())) { llmName = candidate; break; }
                    }
                }
                if(llmName) { char.name = llmName; takenNames.add(llmName.toLowerCase()); }
                saveIdentity(char);
                renderSidebar(searchInput.value);
                
                // Now generate personality
                let pContext = `Context: A magical avatar named ${char.name} specializes in ${char.subtext}.\nCommand: Write exactly one short, eccentric sentence describing their speaking style and demeanor.\nPersonality:`;
                const pData = await llmGenerate({ prompt: pContext, max_length: 60, temperature: 0.8, stop_sequence: ["\n"] });
                let llmPers = pData.results[0].text.trim();
                char.personality = llmPers || `A dedicated and whimsical expert in ${char.subtext}.`;
                saveIdentity(char);
            } catch(e) {
                console.error("Failed to generate details:", e);
                char.personality = `A dedicated expert in ${char.subtext}.`;
                saveIdentity(char);
            }
        } else if (!char.personality) {
            char.personality = `A dedicated expert in ${char.subtext}.`;
            saveIdentity(char);
        }
    }
}

async function runFirstTimeSetup() {
    // Show a non-blocking status banner instead of a full overlay
    // so users can watch the sidebar populate in real-time
    const statusBanner = document.createElement('div');
    statusBanner.id = 'setup-banner';
    statusBanner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;' +
        'background:linear-gradient(135deg,rgba(30,10,60,0.95),rgba(60,20,100,0.95));' +
        'color:#e0d0ff;padding:12px 24px;text-align:center;font-size:14px;' +
        'border-bottom:2px solid rgba(180,100,255,0.5);backdrop-filter:blur(8px);' +
        'box-shadow:0 4px 20px rgba(0,0,0,0.5);';
    statusBanner.innerHTML = '<strong>First-Time Setup</strong> — Conjuring wizard avatars... <span id="setup-progress"></span>';
    document.body.appendChild(statusBanner);
    const progressEl = document.getElementById('setup-progress');

    // 1. Generate Avatars one by one — sidebar updates live
    for(let i=0; i<characters.length; i++) {
        let char = characters[i];
        progressEl.textContent = `(${i+1}/${characters.length}: ${char.name || char.id})`;
        try {
            const avatarRes = await fetch('/api/avatar_generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: char.id, comfy_url: comfyUrl })
            });
            const aData = await avatarRes.json();
            if(aData.avatar_url) {
                char.avatar_url = aData.avatar_url;
                saveIdentity(char);
            }
        } catch(e) { console.error(e); }
        // Re-render sidebar after each avatar so the user sees it appear
        renderSidebar(searchInput.value);
    }

    // 2. Generate a Guild Background
    statusBanner.innerHTML = '<strong>First-Time Setup</strong> — Synthesizing guild background...';
    if(characters.length > 0) {
        try {
            const setupBgRes = getOptimalBgResolution();
            const bgRes = await fetch('/api/background_generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: characters[0].id, comfy_url: comfyUrl, width: setupBgRes.width, height: setupBgRes.height })
            });
            const bData = await bgRes.json();
            if(bData.bg_url) {
                localStorage.setItem('guild_global_bg', bData.bg_url);
                applyGlobalBackground();
            }
        } catch(e) { console.error(e); }
    }

    localStorage.setItem('guild_setup_complete', 'true');
    statusBanner.remove();

    // 3. (Animated avatars are now manual via the Animate All button)

    // 4. Post-setup: prompt user to review & banish misidentified models
    addSystemMessage(
        '<strong>Setup Complete!</strong><br>' +
        'The Guild has detected all models in ComfyUI and generated wizard avatars. ' +
        'However, some models may have been <strong>misidentified as image generators</strong> ' +
        '(e.g. video models, upscalers, 3D models, lighting models). ' +
        'Opening the <em>Banish</em> menu so you can review and dismiss any that don\'t belong.'
    );
    // Open the settings modal after a short delay so the message is visible
    setTimeout(() => {
        settingsModal.classList.remove('hidden');
        loadAndCacheWizards();
    }, 1500);
}

async function generateMissingAvatars() {
    // Find characters that don't have avatars yet (new models added since last run)
    let savedIdentities = JSON.parse(localStorage.getItem('guild_identities') || '{}');
    const missing = characters.filter(c => !c.avatar_url && !savedIdentities[c.id]?.avatar_url);
    if (missing.length === 0) return;

    console.log(`[Guild] Generating avatars for ${missing.length} new wizard(s)...`);
    // Non-blocking banner instead of full overlay
    const banner = document.createElement('div');
    banner.id = 'setup-banner';
    banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;' +
        'background:linear-gradient(135deg,rgba(30,10,60,0.95),rgba(60,20,100,0.95));' +
        'color:#e0d0ff;padding:10px 24px;text-align:center;font-size:13px;' +
        'border-bottom:2px solid rgba(180,100,255,0.5);backdrop-filter:blur(8px);';
    banner.innerHTML = `<strong>Generating ${missing.length} new avatar(s)</strong> — <span id="setup-progress"></span>`;
    document.body.appendChild(banner);
    const prog = document.getElementById('setup-progress');

    for (let i = 0; i < missing.length; i++) {
        let char = missing[i];
        prog.textContent = `${i+1}/${missing.length}: ${char.name}`;
        try {
            const avatarRes = await fetch('/api/avatar_generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: char.id, comfy_url: comfyUrl })
            });
            const aData = await avatarRes.json();
            if (aData.avatar_url) {
                char.avatar_url = aData.avatar_url;
                saveIdentity(char);
            }
        } catch(e) { console.error(`Avatar gen failed for ${char.id}:`, e); }
        // Re-render sidebar after each so avatars appear live
        renderSidebar(searchInput.value);
    }
    banner.remove();
}

// ── Animated avatar queue system (now manual, not auto) ──────────────
let _animPollInterval = null;

// Show "Animate All" button only when video models are detected
async function checkVideoModelAvailable() {
    const btn = document.getElementById('animate-all-btn');
    if (!btn) return;
    btn.style.display = 'inline-flex';  // always visible
    try {
        const res = await fetch('/api/has_video_model');
        const data = await res.json();
        if (data.has_video_model) {
            btn.disabled = false;
            btn.title = 'Animate all wizard avatars using ' + (data.engine || 'video').toUpperCase() +
                ' (queues to ComfyUI in background)';
            btn.dataset.savedTitle = btn.title;
            btn.dataset.videoModelOk = '1';
        } else {
            btn.disabled = true;
            btn.title = 'No video model detected in ComfyUI (needs WAN, LTX, SVD, or CogVideo)';
            btn.dataset.videoModelOk = '0';
        }
    } catch(e) {
        btn.disabled = true;
        btn.title = 'Cannot check for video models — ComfyUI may be offline';
        btn.dataset.videoModelOk = '0';
    }
    // Apply the avatar-completeness gate on top of the video-model gate.
    // _refreshAnimateAllButtonGate disables the button if any wizard
    // still lacks a portrait (you can't animate an empty image).
    _refreshAnimateAllButtonGate();
}

function onAnimateAllClick() {
    const btn = document.getElementById('animate-all-btn');
    if (!btn) return;
    btn.disabled = true;
    btn.innerHTML = '\u2728 Animating...';
    queueAnimatedAvatars().then(() => {
        btn.disabled = false;
        btn.innerHTML = '\u2728 Animate All Avatars';
    });
}

// Wizard types that ship with Spellcaster (mirrors the `core_types`
// set in tavern/server.py's /api/wizard_info). Shipped wizards already
// have hand-tuned portraits so regenerating animations for them on
// every Animate-All click burns user VRAM + minutes for no visible
// gain. Keep opt-in — the "Include built-in wizards" checkbox next
// to the button is the explicit override.
const _CORE_WIZARD_TYPES = new Set(["studio", "model_wizard", "spellcaster_node"]);

function _isCoreWizard(c) {
    return !!(c && _CORE_WIZARD_TYPES.has(c.type));
}

async function queueAnimatedAvatars() {
    // Find characters that have a static avatar but no animated one.
    // Skip shipped Spellcaster wizards unless the user opted in via
    // the toggle — they ship with canonical portraits and animating
    // them by default clogs the ComfyUI queue for no user benefit.
    let savedIdentities = JSON.parse(localStorage.getItem('guild_identities') || '{}');
    const includeCore = !!document.getElementById('animate-all-include-core')?.checked;
    let coreSkipped = 0;
    const needsAnimation = characters.filter(c => {
        const saved = savedIdentities[c.id];
        const hasStatic = c.avatar_url || saved?.avatar_url;
        const hasAnimated = c.animated_url || saved?.animated_url;
        if (!hasStatic || hasAnimated) return false;
        if (!includeCore && _isCoreWizard(c)) {
            coreSkipped++;
            return false;
        }
        return true;
    });

    if (coreSkipped > 0) {
        console.log(`[Guild] Skipped ${coreSkipped} built-in wizard(s) — tick "Include built-in wizards" to animate them too.`);
    }

    if (needsAnimation.length === 0) {
        if (coreSkipped > 0) {
            addSystemMessage(
                `<strong>Nothing to animate.</strong> ${coreSkipped} built-in ` +
                `wizard(s) were skipped. Enable <em>Include built-in wizards</em> ` +
                `under the Animate All button to regenerate their animations.`);
        }
        return;
    }

    console.log(`[Guild] Queuing ${needsAnimation.length} animated avatar(s) to ComfyUI...`);

    // Fire all queue requests in parallel (non-blocking — just adds to ComfyUI queue)
    let queued = 0;
    for (const char of needsAnimation) {
        const staticUrl = char.avatar_url || savedIdentities[char.id]?.avatar_url;
        if (!staticUrl) continue;

        try {
            const res = await fetch('/api/animated_avatar_queue', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    id: char.id,
                    static_avatar_url: staticUrl,
                    comfy_url: comfyUrl,
                })
            });
            const data = await res.json();
            if (data.status === 'queued') {
                queued++;
            } else if (data.status === 'unavailable') {
                console.log(`[Guild] WAN not available: ${data.reason}`);
                return; // No point queuing the rest
            }
        } catch(e) {
            console.error(`Queue failed for ${char.id}:`, e);
            return;
        }
    }

    if (queued === 0) return;
    console.log(`[Guild] ${queued} animated avatar(s) queued. Polling for results...`);

    // Start polling for completion every 5 seconds
    if (_animPollInterval) clearInterval(_animPollInterval);
    _animPollInterval = setInterval(pollAnimatedAvatars, 5000);
}

async function pollAnimatedAvatars() {
    try {
        const res = await fetch('/api/animated_avatar_poll');
        const status = await res.json();

        let allDone = true;
        let anyNew = false;

        for (const [charId, info] of Object.entries(status)) {
            if (info.status === 'queued') {
                allDone = false;
                continue;
            }
            if (info.status === 'done' && info.result_url) {
                const char = characters.find(c => c.id === charId);
                if (char && !char.animated_url) {
                    char.animated_url = info.result_url;
                    saveIdentity(char);
                    anyNew = true;
                    console.log(`[Guild] Animated avatar ready: ${char.name}`);
                }
            }
            // 'error' status — just skip, already logged server-side
        }

        if (anyNew) {
            renderSidebar(searchInput.value);
            // Update header avatar if the active character got an animation
            const active = characters.find(c => c.id === activeCharacterId);
            if (active && active.animated_url) {
                const existingVideo = activeAvatar.querySelector('video');
                if (!existingVideo) {
                    activeAvatar.classList.add('avatar-animated');
                    const vid = document.createElement('video');
                    vid.src = active.animated_url;
                    vid.autoplay = true; vid.loop = true;
                    vid.muted = true; vid.playsInline = true;
                    activeAvatar.appendChild(vid);
                }
            }
        }

        if (allDone) {
            console.log('[Guild] All animated avatars complete.');
            clearInterval(_animPollInterval);
            _animPollInterval = null;
        }
    } catch(e) {
        console.error('[Guild] Poll failed:', e);
    }
}

function applyGlobalBackground() {
    let bgUrl = localStorage.getItem('guild_global_bg');
    if (!bgUrl) {
        const serverBg = _serverGeneratedAssets?.['_global']?.bg_url;
        if (serverBg) {
            bgUrl = serverBg;
            localStorage.setItem('guild_global_bg', bgUrl);
        }
    }
    if (!bgUrl) return;
    // Idempotency guard. The Archivist setup poll calls this function
    // every 2 seconds, and we previously re-set the background-image
    // (a no-op in CSS) AND ran a GSAP body brightness fromTo every
    // single time, which strobed the entire screen on every poll. We
    // now bail out unless the URL actually changed.
    if (document.body.dataset.bgUrl === bgUrl) return;
    document.body.dataset.bgUrl = bgUrl;
    document.body.style.backgroundImage = `url('${bgUrl}')`;
    document.body.style.backgroundSize = "cover";
    document.body.style.backgroundPosition = "center";
    document.body.style.backgroundRepeat = "no-repeat";
    document.body.style.backgroundAttachment = "fixed";
    // No GSAP brightness/saturate transition. The previous version
    // ran gsap.fromTo(body, brightness(1.5)→brightness(1), 1.5s) on
    // every call, which combined with the 2-second poll cadence
    // produced a near-continuous full-screen strobe. The new
    // background just appears.
}

// Helper to get optimal background resolution for user's display
function getOptimalBgResolution() {
    const dpr = window.devicePixelRatio || 1;
    const w = Math.round(window.screen.width * dpr);
    const h = Math.round(window.screen.height * dpr);
    // Clamp to reasonable generation limits (max 2048 on longest side)
    const maxDim = 2048;
    const scale = Math.min(1, maxDim / Math.max(w, h));
    // Round to nearest 64 for optimal VAE processing
    const rw = Math.round((w * scale) / 64) * 64;
    const rh = Math.round((h * scale) / 64) * 64;
    return { width: Math.max(rw, 512), height: Math.max(rh, 512) };
}

function saveIdentity(char) {
    const identity = {
        name: char.name,
        personality: char.personality,
        avatar_url: char.avatar_url,
        animated_url: char.animated_url || undefined,
        _user_renamed: char._user_renamed || undefined,
    };
    let savedIdentities = JSON.parse(localStorage.getItem('guild_identities') || '{}');
    savedIdentities[char.id] = identity;
    localStorage.setItem('guild_identities', JSON.stringify(savedIdentities));
    // Invalidate tooltip cache so hover bubble syncs immediately
    if (typeof _tooltipCache !== 'undefined') {
        delete _tooltipCache[char.id];
    }
    // Persist to server (fire-and-forget)
    fetch('/api/wizard_identities', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({identities: {[char.id]: identity}}),
    }).catch(() => {});
}

// ── Avatar placeholder + pending state ───────────────────────────────
//
// Wizards without a generated portrait fall back to the Spellcaster icon
// (served by /api/placeholder_avatar). Two animation states layered on
// top of the placeholder tell the user what's happening:
//
//   queued   — slow fade, low opacity. Wizard is in the setup queue
//              waiting for ComfyUI to get to it.
//   active   — fast fade, full opacity. ComfyUI is generating this
//              wizard's portrait right now.
//
// _avatarStateForChar picks the right state based on the current setup
// snapshot (see _archivistRefreshSidebarPending below).

const _PLACEHOLDER_AVATAR_URL = '/api/placeholder_avatar';

// Map: charId -> 'active' | 'queued' | undefined
let _avatarPendingState = {};

function _avatarStateForChar(char) {
    if (!char) return null;
    if (char.avatar_url) return null;
    return _avatarPendingState[char.id] || 'queued';
}

function _avatarHtmlForCard(char, gradient) {
    // Returns the inner HTML for a sidebar card's avatar div.
    //
    // POLICY: when an animated avatar exists, render BOTH a still <img>
    // sibling AND the <video>, layered inside the .avatar-animated div.
    // The still is always in the DOM at opacity 1; the video sits on
    // top at opacity 0 until it fires `playing`, at which point the
    // still fades out. On `pause` / `stalled` / `emptied` / `error`
    // the still fades back in.
    //
    // Why: real Chrome aggressively throttles <video> elements when
    // the tab has many simultaneous autoplay loops (we have 34+ wizards
    // in the sidebar). A throttled video briefly renders a blank frame
    // that fully covers the div's background, making the avatar look
    // "disappeared" for a split second before Chrome resumes decoding.
    // Layering a persistent still underneath means something visible
    // is ALWAYS painted there, whether or not the browser feels like
    // decoding video this tick.
    if (char.animated_url) {
        const still = char.avatar_url || _PLACEHOLDER_AVATAR_URL;
        const poster = char.avatar_url
            ? ` poster="${char.avatar_url}"` : '';
        return `
            <div class="avatar avatar-animated" style="background: ${gradient};">
                <img class="avatar-still" src="${still}" alt="" loading="lazy" />
                <video src="${char.animated_url}"${poster} autoplay loop muted playsinline preload="metadata"></video>
            </div>`;
    }
    if (char.avatar_url) {
        return `
            <div class="avatar" style="background: ${gradient}; background-image: url('${char.avatar_url}');"></div>`;
    }
    // Placeholder branch
    const state = _avatarStateForChar(char) || 'queued';
    return `
        <div class="avatar avatar-placeholder pending-${state}" style="background: ${gradient}; background-image: url('${_PLACEHOLDER_AVATAR_URL}');"></div>`;
}

// ── Animated-avatar resilience ──────────────────────────────────────
// Attach playing/stalled/pause/error listeners to every animated
// avatar's <video> so the layered still PNG fades in whenever the
// video isn't actively painting frames. Idempotent + delegated so
// dynamically-inserted cards get wired up automatically.
function _armAvatarVideo(vid) {
    if (!vid || vid._avatarArmed) return;
    vid._avatarArmed = true;
    const wrap = vid.closest('.avatar-animated');
    if (!wrap) return;
    const still = wrap.querySelector('.avatar-still');
    const show = () => { wrap.classList.remove('avatar-video-live'); };
    const hide = () => { wrap.classList.add('avatar-video-live'); };
    // Default state = still visible, video hidden. Becomes "video
    // live" only after we get a `playing` event, and flips back on
    // any of the events that signal the video stopped painting.
    show();
    vid.addEventListener('playing', hide);
    vid.addEventListener('pause', show);
    vid.addEventListener('stalled', show);
    vid.addEventListener('suspend', show);
    vid.addEventListener('emptied', show);
    vid.addEventListener('error', show);
    vid.addEventListener('ended', show);   // loop=true usually prevents this; defensive
}
// One-time mutation observer — arms every new .avatar-animated video.
(function _watchAvatarVideos() {
    if (typeof document === 'undefined' || document._avatarObserverAttached) return;
    document._avatarObserverAttached = true;
    const arm = (root) => {
        root.querySelectorAll('.avatar-animated video').forEach(_armAvatarVideo);
    };
    // Arm anything already in the DOM
    arm(document);
    // And anything that shows up later
    try {
        new MutationObserver(records => {
            for (const r of records) {
                r.addedNodes.forEach(n => {
                    if (n.nodeType === 1) {
                        if (n.matches && n.matches('.avatar-animated video')) {
                            _armAvatarVideo(n);
                        } else if (n.querySelectorAll) {
                            arm(n);
                        }
                    }
                });
            }
        }).observe(document.body, { childList: true, subtree: true });
    } catch (_e) { /* browsers without MutationObserver just get the eager pass */ }
})();

function _refreshAnimateAllButtonGate() {
    // Disable "Animate All Avatars" while ANY wizard's portrait is
    // still missing. You can't animate an empty image — wait until
    // every initial avatar has finished.
    const btn = document.getElementById('animate-all-btn');
    if (!btn) return;
    const everyoneHasAvatar = (typeof characters !== 'undefined')
        && characters.every(c => !!c.avatar_url);
    if (everyoneHasAvatar) {
        // Allow the existing video-model gate to take over (don't override
        // it — checkVideoModelAvailable owns the "no video model" state)
        if (btn.dataset.setupBlocked === '1') {
            btn.dataset.setupBlocked = '0';
            btn.disabled = false;
            btn.title = btn.dataset.savedTitle ||
                'Animate all wizard avatars (queues to ComfyUI in background)';
            btn.classList.remove('setup-blocked');
        }
    } else {
        if (btn.dataset.setupBlocked !== '1') {
            btn.dataset.savedTitle = btn.title;
        }
        btn.dataset.setupBlocked = '1';
        btn.disabled = true;
        btn.title = "Wait until every wizard's portrait has been generated.";
        btn.classList.add('setup-blocked');
    }
}

function _refreshSidebarPlaceholders() {
    // Walk every rendered card in the sidebar and update its avatar's
    // placeholder/pending classes to match the current state. Used after
    // each /api/setup/status poll so the queued/active animation moves
    // along with the background generation.
    if (!characterList) return;
    const cards = characterList.querySelectorAll('.character-card[data-id]');
    cards.forEach(card => {
        const cid = card.dataset.id;
        const char = (typeof characters !== 'undefined')
            ? characters.find(c => c.id === cid) : null;
        if (!char) return;
        const av = card.querySelector('.avatar');
        if (!av) return;
        // Already has a portrait? clear placeholder state.
        if (char.avatar_url) {
            av.classList.remove('avatar-placeholder', 'pending-queued', 'pending-active');
            return;
        }
        // Missing — apply placeholder + the right pending class
        av.classList.add('avatar-placeholder');
        av.style.backgroundImage = `url('${_PLACEHOLDER_AVATAR_URL}')`;
        const state = _avatarStateForChar(char) || 'queued';
        av.classList.toggle('pending-active', state === 'active');
        av.classList.toggle('pending-queued', state !== 'active');
    });
    _refreshAnimateAllButtonGate();
}

// ── Model architecture metadata ─────────────────────────────────────
// Every per-model wizard carries a model_arch key (sdxl, flux2klein, …).
// This table turns those opaque keys into a sidebar sub-header: full
// human name, vibe-appropriate accent gradient, display order, and a
// rune emoji that hints at the arch's personality. Keep `order` tight
// — the sidebar is vertical and wizards you're most likely to pick
// should be at the top. video/unknown live at the bottom.
//
// Used by:
//   - renderSidebar()        → groups per-model wizards under an
//                              ".arch-group-<key>" sub-header
//   - showWizardTooltip()    → colours the Model section's arch badge
//                              and prints the full name
//   - character-card         → subtle left border tint per arch so
//                              scanning the sidebar you can tell
//                              which family each wizard belongs to.
const ARCH_META = {
    // — Flagship flow-matching / diffusion flagships (2025) —
    flux2klein:   { fullName: "Flux 2 Klein",        short: "Klein",
                    order: 10, icon: "✦",
                    c1: "#ffd700", c2: "#b470ff",
                    glow: "255,215,0" },
    flux1dev:     { fullName: "Flux 1 Dev",          short: "Flux",
                    order: 20, icon: "◈",
                    c1: "#58e0ff", c2: "#ffd700",
                    glow: "88,224,255" },
    flux_kontext: { fullName: "Flux Kontext",        short: "Kontext",
                    order: 25, icon: "◆",
                    c1: "#7ab6ff", c2: "#c6e0ff",
                    glow: "122,182,255" },
    chroma:       { fullName: "Chroma",              short: "Chroma",
                    order: 30, icon: "❋",
                    c1: "#ff7ad7", c2: "#7af0ff",
                    glow: "255,122,215" },
    sd3:          { fullName: "Stable Diffusion 3",  short: "SD3",
                    order: 35, icon: "△",
                    c1: "#a68eff", c2: "#e7ddff",
                    glow: "166,142,255" },
    sd3_turbo:    { fullName: "Stable Diffusion 3.5 Turbo", short: "SD3.5T",
                    order: 37, icon: "⚡",
                    c1: "#ffee58", c2: "#a68eff",
                    glow: "255,238,88" },

    // — SDXL & relatives —
    sdxl:         { fullName: "Stable Diffusion XL", short: "SDXL",
                    order: 40, icon: "✹",
                    c1: "#b470ff", c2: "#ffc667",
                    glow: "180,112,255" },
    sdxl_turbo:   { fullName: "SDXL Turbo",          short: "SDXL-T",
                    order: 45, icon: "⚡",
                    c1: "#ffc667", c2: "#ff7a6b",
                    glow: "255,198,103" },
    illustrious:  { fullName: "Illustrious",         short: "Illus.",
                    order: 50, icon: "❀",
                    c1: "#ff8fd1", c2: "#ffd1ed",
                    glow: "255,143,209" },
    pony:         { fullName: "Pony Diffusion",      short: "Pony",
                    order: 55, icon: "❀",
                    c1: "#ff6bb5", c2: "#ffce5e",
                    glow: "255,107,181" },

    // — Classic SD1.5 —
    sd15:         { fullName: "Stable Diffusion 1.5", short: "SD1.5",
                    order: 60, icon: "✧",
                    c1: "#8aa9ff", c2: "#c9d7ff",
                    glow: "138,169,255" },

    // — Speed-focused —
    zit:          { fullName: "Z-Image Turbo",       short: "ZIT",
                    order: 70, icon: "⚡",
                    c1: "#ffef4a", c2: "#a6ff6b",
                    glow: "255,239,74" },

    // — Niche DiT/transformer —
    hunyuan_dit:  { fullName: "Hunyuan DiT",         short: "HY-DiT",
                    order: 80, icon: "龍",
                    c1: "#ff8a5c", c2: "#ffcfa8",
                    glow: "255,138,92" },
    pixart:       { fullName: "PixArt",              short: "PixArt",
                    order: 82, icon: "▦",
                    c1: "#6bd9b5", c2: "#bff0dc",
                    glow: "107,217,181" },
    auraflow:     { fullName: "AuraFlow",            short: "Aura",
                    order: 85, icon: "◎",
                    c1: "#a8e0ff", c2: "#d8c3ff",
                    glow: "168,224,255" },
    kolors:       { fullName: "Kolors",              short: "Kolors",
                    order: 88, icon: "◍",
                    c1: "#ff8fa3", c2: "#8fe0ff",
                    glow: "255,143,163" },
    playground:   { fullName: "Playground v2.5",     short: "PG2.5",
                    order: 90, icon: "◒",
                    c1: "#ffb4a8", c2: "#ffe0d4",
                    glow: "255,180,168" },

    // — Video —
    ltx2:         { fullName: "LTX Video",           short: "LTX",
                    order: 100, icon: "◉",
                    c1: "#5eead4", c2: "#c4b5fd",
                    glow: "94,234,212" },
    ltx:          { fullName: "LTX Video",           short: "LTX",
                    order: 100, icon: "◉",
                    c1: "#5eead4", c2: "#c4b5fd",
                    glow: "94,234,212" },
    wan22:        { fullName: "Wan 2.2 Video",       short: "Wan",
                    order: 105, icon: "◉",
                    c1: "#10b981", c2: "#6ee7b7",
                    glow: "16,185,129" },
    wan:          { fullName: "Wan 2.2 Video",       short: "Wan",
                    order: 105, icon: "◉",
                    c1: "#10b981", c2: "#6ee7b7",
                    glow: "16,185,129" },

    // Fallback bucket for anything the server hasn't classified yet.
    unknown:      { fullName: "Other Models",        short: "Other",
                    order: 900, icon: "❔",
                    c1: "#888888", c2: "#cccccc",
                    glow: "160,160,160" },
};

// Resolve a character's arch key → ARCH_META entry. Handles both the
// typed comfyui_model (has `model_arch`) and the legacy model_wizard
// (LTX / WAN — we infer from id or name).
function _archKeyForChar(char) {
    if (char.model_arch) return char.model_arch;
    const id = (char.id || '').toLowerCase();
    const name = (char.name || '').toLowerCase();
    if (id.includes('ltx') || name.includes('ltx')) return 'ltx2';
    if (id.includes('wan') || name.includes('wan')) return 'wan22';
    return 'unknown';
}
function _archMeta(archKey) {
    return ARCH_META[archKey] || ARCH_META.unknown;
}
// Exposed so the tooltip (and any future surface) can read the same
// theme without duplicating the table.
window.ARCH_META = ARCH_META;
window._archMeta = _archMeta;
window._archKeyForChar = _archKeyForChar;

function renderSidebar(filter = "") {
    characterList.innerHTML = '';
    const lowFilter = filter.toLowerCase();

    // Separate core wizards (studio + model_wizard) from per-model wizards (comfyui_model, custom_*)
    const coreTypes = new Set(['studio', 'model_wizard', 'spellcaster_node']);
    const coreChars = characters.filter(c => coreTypes.has(c.type));
    const modelChars = characters.filter(c => !coreTypes.has(c.type));

    let addedSeparator = false;

    function renderCard(char) {
        if (filter && !char.name.toLowerCase().includes(lowFilter) && !char.subtext.toLowerCase().includes(lowFilter)) {
            return;
        }

        const card = document.createElement('div');
        card.className = 'character-card';
        if (_sidebarRevealed) card.classList.add('revealed');
        if (char.id === activeCharacterId) card.classList.add('active');
        card.dataset.id = char.id;

        const gradient = `linear-gradient(135deg, ${char.color1}, ${char.color2})`;
        // Avatar HTML — handles avatar_url, animated_url, and the
        // placeholder/pending fallback in one place.
        // char.name / char.subtext come from SillyTavern-format cards
        // which are user-imported from external sources (Chub etc.) —
        // treat as attacker-controlled.
        card.innerHTML = `
            ${_avatarHtmlForCard(char, gradient)}
            <div class="character-info">
                <h3>${_esc(char.name)}</h3>
                <p>${_esc(char.subtext)}</p>
            </div>
        `;

        card.addEventListener('click', () => { selectCharacter(char.id); onMobileCharacterSelect(); });

        // ── Wizard info tooltip on hover ──
        let hoverTimer = null;
        card.addEventListener('mouseenter', () => {
            _tooltipHoverIntent = true;
            hoverTimer = setTimeout(() => showWizardTooltip(char, card), 420);
        });
        card.addEventListener('mouseleave', () => {
            _tooltipHoverIntent = false;
            clearTimeout(hoverTimer);
            // Delay hide so user can move mouse to the tooltip itself
            setTimeout(() => {
                if (!_tooltipHoverIntent && !_tooltipHovering) hideWizardTooltip();
            }, 150);
        });

        characterList.appendChild(card);
    }

    // Add "Core Spellcasters" header if there are visible core wizards
    if (coreChars.length > 0) {
        const hasVisibleCore = coreChars.some(c =>
            !filter || c.name.toLowerCase().includes(lowFilter) || c.subtext.toLowerCase().includes(lowFilter)
        );
        if (hasVisibleCore) {
            const coreSep = document.createElement('div');
            coreSep.className = 'sidebar-separator';
            coreSep.style.paddingTop = '4px';
            coreSep.innerHTML = '<span>Core Spellcasters</span>';
            characterList.appendChild(coreSep);
        }
    }

    coreChars.forEach(renderCard);

    // Per-Model Wizards — grouped by architecture. Each arch gets its
    // own themed sub-header so users can scan the sidebar and tell
    // "these are my SDXL wizards, these are my Flux 2 Klein wizards"
    // without reading every subtext. The umbrella "Per-Model Wizards"
    // separator still appears on top when there are also core wizards
    // above, so the visual hierarchy is:
    //   Core Spellcasters
    //     · Spellcaster, Imaginus, …
    //   Per-Model Wizards
    //     · Flux 2 Klein          ← arch sub-header (themed)
    //         · Fluxx the Whisperer
    //         · Flux Whisperer
    //     · Stable Diffusion XL   ← arch sub-header (themed)
    //         · Albedo the Luminous
    //         · …
    const matchesFilter = (c) =>
        !filter || c.name.toLowerCase().includes(lowFilter)
                || c.subtext.toLowerCase().includes(lowFilter);
    const hasVisibleModels = modelChars.some(matchesFilter);
    if (hasVisibleModels && coreChars.length > 0) {
        const sep = document.createElement('div');
        sep.className = 'sidebar-separator';
        sep.innerHTML = '<span>Per-Model Wizards</span>';
        characterList.appendChild(sep);
    }

    // Group by arch, preserve insertion order within each group.
    const byArch = {};
    for (const c of modelChars) {
        const archKey = _archKeyForChar(c);
        (byArch[archKey] = byArch[archKey] || []).push(c);
    }
    // Sort archs by display order (defined in ARCH_META). Missing
    // archs get pushed to the end via the `unknown` fallback.
    const orderedArchs = Object.keys(byArch).sort((a, b) =>
        (_archMeta(a).order || 999) - (_archMeta(b).order || 999));

    for (const archKey of orderedArchs) {
        const group = byArch[archKey];
        if (!group.some(matchesFilter)) continue;   // filter hid them all

        const meta = _archMeta(archKey);
        const header = document.createElement('div');
        header.className = `sidebar-arch-header arch-${archKey}`;
        header.style.setProperty('--arch-c1', meta.c1);
        header.style.setProperty('--arch-c2', meta.c2);
        header.style.setProperty('--arch-glow', meta.glow);
        header.innerHTML = `
            <span class="arch-rune">${meta.icon}</span>
            <span class="arch-name">${meta.fullName}</span>
            <span class="arch-count">${group.filter(matchesFilter).length}</span>`;
        characterList.appendChild(header);
        for (const char of group) {
            if (!matchesFilter(char)) continue;
            renderCard(char);
            // Last rendered card picks up the arch class so a subtle
            // left-border tint signals the group at a glance even
            // when sub-headers scroll off.
            const last = characterList.lastElementChild;
            if (last && last.classList.contains('character-card')) {
                last.classList.add(`arch-${archKey}`);
                last.style.setProperty('--arch-c1', meta.c1);
                last.style.setProperty('--arch-c2', meta.c2);
                last.style.setProperty('--arch-glow', meta.glow);
            }
        }
    }
}

searchInput.addEventListener('input', (e) => {
    renderSidebar(e.target.value);
});

// ── Wizard Info Tooltip ──────────────────────────────────────────

let _wizardTooltip = null;
let _tooltipCache = {};  // Cache fetched info to avoid re-fetching
let _tooltipDismissTimer = null;
let _tooltipEscHandler = null;
let _tooltipOutsideHandler = null;
let _tooltipHoverIntent = false;  // true while mouse is over a card
let _tooltipHovering = false;     // true while mouse is over the tooltip itself
let _tooltipGeneration = 0;       // increments on each show, stale async checks against this

function hideWizardTooltip() {
    _tooltipGeneration++;
    _tooltipHovering = false;
    if (_tooltipDismissTimer) {
        clearTimeout(_tooltipDismissTimer);
        _tooltipDismissTimer = null;
    }
    if (_wizardTooltip) {
        _wizardTooltip.remove();
        _wizardTooltip = null;
    }
    if (_tooltipEscHandler) {
        document.removeEventListener('keydown', _tooltipEscHandler);
        _tooltipEscHandler = null;
    }
    if (_tooltipOutsideHandler) {
        document.removeEventListener('click', _tooltipOutsideHandler);
        _tooltipOutsideHandler = null;
    }
}

async function showWizardTooltip(char, cardEl) {
    hideWizardTooltip();
    const myGen = ++_tooltipGeneration;

    // Set auto-dismiss timer (reset if user hovers the tooltip)
    _tooltipDismissTimer = setTimeout(hideWizardTooltip, 8000);

    // Fetch detailed info (cached)
    let info = _tooltipCache[char.id];
    if (!info) {
        try {
            const resp = await fetch(`/api/wizard_info/${char.id}`);
            if (!resp.ok) return;
            info = await resp.json();
            _tooltipCache[char.id] = info;
        } catch { return; }
    }

    // Stale check: if another show/hide happened during async fetch, abort
    if (_tooltipGeneration !== myGen) return;

    // Build tooltip content
    const tooltip = document.createElement('div');
    tooltip.className = 'wizard-tooltip';

    // Avatar + header
    const avatarUrl = char.avatar_url || `/api/avatar/${char.id}`;
    const gradient = `linear-gradient(135deg, ${info.color1}, ${info.color2})`;

    // Category badge
    const catClass = info.is_core ? 'wt-badge-core' : 'wt-badge-model';
    const catLabel = info.is_core ? 'Core Spellcaster' : 'Per-Model Wizard';

    // Build functions list
    let fnHtml = '';
    if (info.build_fns && info.build_fns.length > 0) {
        const fns = info.build_fns.slice(0, 6).map(f =>
            `<span class="wt-fn-tag">${f.replace('build_', '')}</span>`
        ).join('');
        const extra = info.build_fn_count > 6 ? `<span class="wt-fn-extra">+${info.build_fn_count - 6} more</span>` : '';
        fnHtml = `<div class="wt-section"><div class="wt-section-label">Capabilities</div><div class="wt-fn-list">${fns}${extra}</div></div>`;
    }

    // Model info. Arch badge picks up the ARCH_META theme so hover-
    // over-GIMP and hover-over-Flux look instantly different even
    // before the user reads the label. full name beats the raw key.
    let modelHtml = '';
    if (info.model_name) {
        const shortModel = info.model_name.split(/[/\\]/).pop();
        const archKey = info.model_arch || _archKeyForChar(char) || 'unknown';
        const meta = _archMeta(archKey);
        const badgeStyle =
            `background:linear-gradient(135deg, ${meta.c1}, ${meta.c2});` +
            `box-shadow:0 0 10px rgba(${meta.glow},0.45), ` +
                       `0 0 20px rgba(${meta.glow},0.25);`;
        modelHtml = `<div class="wt-section">
            <div class="wt-section-label">Architecture</div>
            <div class="wt-arch-hero arch-${archKey}"
                 style="--arch-c1:${meta.c1};--arch-c2:${meta.c2};--arch-glow:${meta.glow};">
                <span class="wt-arch-rune">${meta.icon}</span>
                <div class="wt-arch-lines">
                    <div class="wt-arch-full">${meta.fullName}</div>
                    <div class="wt-arch-sub">${archKey}</div>
                </div>
                <span class="wt-arch-badge" style="${badgeStyle}">${meta.short}</span>
            </div>
            <div class="wt-model-row" style="margin-top:6px;">
                <span class="wt-section-label" style="margin-right:6px;">Model</span>
                <span class="wt-model-name" title="${info.model_name}">${shortModel}</span>
            </div>
        </div>`;
    }

    // LoRA summary
    let loraHtml = '';
    const hasAutoset = info.autoset_loras && Object.keys(info.autoset_loras).length > 0;
    const hasPreset = info.preset_loras && Object.keys(info.preset_loras).length > 0;
    if (info.lora_count > 0 || hasAutoset || hasPreset) {
        let loraLines = '';
        // Autoset LoRAs
        if (hasAutoset) {
            for (const [mode, loras] of Object.entries(info.autoset_loras)) {
                for (const l of loras) {
                    loraLines += `<div class="wt-lora-row">
                        <span class="wt-lora-name">${l.name}</span>
                        <span class="wt-lora-str">${l.strength}</span>
                        <span class="wt-lora-badge wt-lora-auto">auto:${mode}</span>
                    </div>`;
                }
            }
        }
        // Preset LoRAs (WAN turbo, LTX distilled)
        if (hasPreset) {
            for (const [key, name] of Object.entries(info.preset_loras)) {
                const label = key.replace('wan_turbo_', 'WAN Turbo ').replace('ltx_distilled', 'LTX Distilled');
                loraLines += `<div class="wt-lora-row">
                    <span class="wt-lora-name">${name}</span>
                    <span class="wt-lora-badge wt-lora-preset">${label}</span>
                </div>`;
            }
        }
        // Compatible LoRAs
        if (info.lora_summary && info.lora_summary.length > 0) {
            for (const l of info.lora_summary) {
                const srcClass = l.source === 'civitai' ? 'wt-lora-civitai' : l.source === 'user' ? 'wt-lora-user' : 'wt-lora-disc';
                const srcLabel = l.source === 'civitai' ? 'CivitAI' : l.source === 'user' ? 'user' : 'found';
                loraLines += `<div class="wt-lora-row">
                    <span class="wt-lora-name">${l.name}</span>
                    ${l.purpose ? `<span class="wt-lora-purpose">${l.purpose}</span>` : ''}
                    <span class="wt-lora-badge ${srcClass}">${srcLabel}</span>
                </div>`;
            }
        }
        const extraCount = info.lora_count > 8 ? `<div class="wt-lora-extra">+${info.lora_count - 8} more compatible LoRAs</div>` : '';
        loraHtml = `<div class="wt-section">
            <div class="wt-section-label">LoRAs (${info.lora_count} compatible)</div>
            <div class="wt-lora-list">${loraLines}${extraCount}</div>
        </div>`;
    }

    // Settings hint
    const settingsHint = info.is_core
        ? '<div class="wt-hint">Core settings — built into the app. Customizable via Travelling Wizard > Scaffolds tab.</div>'
        : '<div class="wt-hint">Auto-generated settings from detected model. Edit in Travelling Wizard > Scaffolds tab.</div>';

    // Personality
    let personHtml = '';
    if (info.personality) {
        personHtml = `<div class="wt-section"><div class="wt-section-label">Personality</div><div class="wt-personality">${_esc(info.personality)}</div></div>`;
    }

    // char.name / char.subtext / avatarUrl all come from imported
    // SillyTavern character cards (attacker-controlled source). Escape
    // text nodes; clamp avatarUrl to http(s) / data:image / /api/.
    const safeAvatar = _safeSrc(avatarUrl);
    tooltip.innerHTML = `
        <button class="wt-close" type="button" title="Close (Esc)" aria-label="Close">&times;</button>
        <div class="wt-header" style="background: ${gradient};">
            <img class="wt-avatar" src="${_esc(safeAvatar)}" alt="" onerror="this.style.display='none'"/>
            <div class="wt-header-text" style="position:relative; width:100%;">
                <div class="wt-name">${_esc(char.name)} ${char.id === activeCharacterId ? '<span title="Currently active wizard" style="margin-left:8px; font-size:16px;">\u2705</span>' : ''}</div>
                <div class="wt-subtext">${_esc(char.subtext)}</div>
                <span class="wt-badge ${catClass}">${_esc(catLabel)}</span>
            </div>
        </div>
        ${personHtml}
        ${modelHtml}
        ${fnHtml}
        ${loraHtml}
        ${settingsHint}
    `;

    // Manual close button — fixes the "tooltip got stuck and won't go
    // away" symptom that happens when the user moves the cursor in a
    // way the mouseleave handler misses (e.g. Alt-tab, fast diagonal
    // exit, browser focus loss).
    const closeBtn = tooltip.querySelector('.wt-close');
    if (closeBtn) {
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            hideWizardTooltip();
        });
    }
    // Escape key as a backup escape hatch
    if (!_tooltipEscHandler) {
        _tooltipEscHandler = (e) => {
            if (e.key === 'Escape' && _wizardTooltip) hideWizardTooltip();
        };
        document.addEventListener('keydown', _tooltipEscHandler);
    }
    // Click outside the tooltip dismisses it too
    if (!_tooltipOutsideHandler) {
        _tooltipOutsideHandler = (e) => {
            if (_wizardTooltip && !_wizardTooltip.contains(e.target)
                && !e.target.closest('.character-card')) {
                hideWizardTooltip();
            }
        };
        // Defer attaching so the click that opened the tooltip doesn't
        // immediately close it
        setTimeout(() => document.addEventListener('click', _tooltipOutsideHandler), 0);
    }

    // Keep tooltip alive while user hovers it (e.g. to read LoRA list)
    tooltip.addEventListener('mouseenter', () => {
        _tooltipHovering = true;
        if (_tooltipDismissTimer) {
            clearTimeout(_tooltipDismissTimer);
            _tooltipDismissTimer = null;
        }
    });
    tooltip.addEventListener('mouseleave', () => {
        _tooltipHovering = false;
        // Auto-dismiss shortly after leaving the tooltip
        _tooltipDismissTimer = setTimeout(hideWizardTooltip, 400);
    });

    // Position tooltip to the right of the card
    document.body.appendChild(tooltip);
    _wizardTooltip = tooltip;

    const cardRect = cardEl.getBoundingClientRect();
    const ttRect = tooltip.getBoundingClientRect();
    let top = cardRect.top;
    let left = cardRect.right + 12;

    // Keep within viewport
    if (top + ttRect.height > window.innerHeight - 10) {
        top = window.innerHeight - ttRect.height - 10;
    }
    if (top < 10) top = 10;
    if (left + ttRect.width > window.innerWidth - 10) {
        left = cardRect.left - ttRect.width - 12;  // flip to left side
    }
    tooltip.style.top = top + 'px';
    tooltip.style.left = left + 'px';
    tooltip.classList.add('wt-visible');
}

// ─── Persistent chat history ───────────────────────────────────────
//
// The Wizard Guild now keeps a permanent JSONL log per wizard on the
// server. Every user/assistant/system message and every successful
// generation is appended; selectCharacter() replays the log so a
// page refresh (or a different device pointing at the same Guild)
// shows the full conversation. Generation records also get a
// "Cast Again" button that re-fires the saved spell payload, with
// optional batching (cast N times).
function _persistChatRecord(record) {
    if (!activeCharacterId) return;
    try {
        fetch('/api/chat_history/append', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ char_id: activeCharacterId, record }),
            keepalive: true,
        }).catch(() => {});
    } catch (e) { /* fire-and-forget */ }
}

async function _loadChatHistoryFor(charId) {
    try {
        const r = await fetch(`/api/chat_history/${encodeURIComponent(charId)}`);
        if (!r.ok) return [];
        const data = await r.json();
        return Array.isArray(data.records) ? data.records : [];
    } catch (e) {
        return [];
    }
}

function _replayChatRecord(rec) {
    if (!rec || typeof rec !== 'object') return;
    const role = rec.role;
    if (role === 'user') {
        addUserMessage(rec.content || '', { skipPersist: true });
    } else if (role === 'assistant') {
        addAIMessage(rec.content || '', { skipPersist: true });
    } else if (role === 'system') {
        addSystemMessage(rec.content || '', { skipPersist: true });
    } else if (role === 'generation') {
        addGenerationMessage(
            rec.payload || {}, rec.type || 'images', rec.urls || [],
            { skipPersist: true });
    }
}

async function selectCharacter(id) {
    activeCharacterId = id;
    const char = characters.find(c => c.id === id);
    if (!char) return;

    renderSidebar(searchInput.value);

    activeName.textContent = char.name;
    activeSubtext.textContent = char.subtext;
    const gradient = `linear-gradient(135deg, ${char.color1}, ${char.color2})`;
    activeAvatar.style.background = gradient;
    const avatarUrl = char.avatar_url || `/api/avatar/${char.id}`;
    activeAvatar.style.backgroundImage = `url('${avatarUrl}')`;

    // Show animated avatar in header if available
    const existingVideo = activeAvatar.querySelector('video');
    if (existingVideo) existingVideo.remove();
    if (char.animated_url) {
        activeAvatar.classList.add('avatar-animated');
        const vid = document.createElement('video');
        vid.src = char.animated_url;
        vid.autoplay = true; vid.loop = true; vid.muted = true; vid.playsInline = true;
        activeAvatar.appendChild(vid);
    } else {
        activeAvatar.classList.remove('avatar-animated');
    }

    // Reset Chat Memory
    chatHistory = [];
    chatStream.innerHTML = '';

    // Replay persistent history first. If nothing on disk, drop the
    // initial greeting and persist it so future loads see it too.
    const history = await _loadChatHistoryFor(id);
    if (history.length) {
        for (const rec of history) {
            chatHistory.push(rec);
            _replayChatRecord(rec);
        }
        // If the only record is a greeting (no user interaction yet), show chips
        if (history.length === 1 && history[0].role === 'assistant') {
            renderStarterChips();
        }
    } else {
        let intro;
        if (char.type === "studio") {
            intro = `Greetings. I am ${char.name}, the Guild's specialist in ${char.subtext}. Describe what you need, and I shall present my tools for you to choose from.`;
        } else {
            intro = `Greetings. I am ${char.name}, master of ${char.subtext}. Tell me what you wish to conjure, and I shall guide your spellcraft.`;
        }
        chatHistory.push({ role: 'assistant', content: intro });
        addAIMessage(intro);
        renderStarterChips();
    }

    // If a pending image is coming in from an "image action chip" on
    // another wizard, drop an attachment bubble + canned message now.
    if (window._pendingImageContext) {
        const ctx = window._pendingImageContext;
        window._pendingImageContext = null;
        _renderPendingAttachment(ctx);
    }

    // GSAP: burst effect on avatar selection
    _avatarSelectBurst(activeAvatar);
}

// Render the starter chip strip below the current greeting.
// Chips send a natural-English phrase to the LLM on click.
function renderStarterChips() {
    if (typeof window.getStarterChips !== 'function') return;
    const chips = window.getStarterChips(activeCharacterId);
    if (!chips || !chips.length) return;

    // Kill any existing strip first (defensive)
    const old = chatStream.querySelector('.starter-chips');
    if (old) old.remove();

    const strip = document.createElement('div');
    strip.className = 'starter-chips';
    chips.forEach(c => {
        const btn = document.createElement('button');
        btn.className = 'option-btn starter-chip';
        btn.innerHTML = `<span class="chip-icon">${c.icon}</span><span class="chip-label">${c.label}</span>`;
        btn.addEventListener('click', () => {
            strip.remove();
            addUserMessage(c.label);
            askKobold(c.message);
        });
        strip.appendChild(btn);
    });
    chatStream.appendChild(strip);
    chatStream.scrollTop = chatStream.scrollHeight;
}

// Called when the user clicked an image-action chip on a DIFFERENT wizard.
// Renders an "attachment" bubble in the new wizard's chat and fires the
// canned message to the LLM.
function _renderPendingAttachment(ctx) {
    const { imageUrl, message } = ctx;
    // Show the image as an attachment bubble (user side)
    const msg = document.createElement('div');
    msg.className = 'message user-message';
    msg.innerHTML = `
        <div class="avatar-small">${USER_SPARKLE_SVG}</div>
        <div class="bubble">
            <p style="font-size:12px;opacity:.8;margin:0 0 6px;">📎 Working with this image:</p>
            <img src="${imageUrl}" class="attachment-image" style="max-width:200px;border-radius:6px;display:block;">
        </div>
    `;
    chatStream.appendChild(msg);
    _persistChatRecord({ role: 'user', content: `[attached image: ${imageUrl}]`, ts: Date.now() / 1000 });

    // Then send the canned LLM message
    addUserMessage(message);
    askKobold(`${message}\n\n[The user has attached this image: ${imageUrl}]`);
}

function _parseNumberedOptions(text) {
    // Split text into prose lines and numbered options.
    // Matches patterns like: "1. Option text", "  2. Do something", "3) Thing"
    // Returns { prose: string, options: [{num: "1", label: "Option text"}, ...] }
    const lines = text.split('\n');
    const prose = [];
    const options = [];
    const optionRe = /^\s*(\d+)[.)]\s+(.+)/;

    for (const line of lines) {
        const m = line.match(optionRe);
        if (m) {
            options.push({ num: m[1], label: m[2].trim() });
        } else {
            prose.push(line);
        }
    }
    return { prose: prose.join('\n').trim(), options };
}

function addAIMessage(text, opts = {}) {
    const msg = document.createElement('div');
    msg.className = 'message ai-message';

    const { prose, options } = _parseNumberedOptions(text);

    let bubbleHTML = '';
    if (prose) {
        // LLM replies arrive in markdown — **bold**, `code`, bullet
        // lists, headings. Render them through the Archivist's markdown
        // helper so the chat bubble doesn't show literal asterisks and
        // hash marks. _renderSimpleMarkdown HTML-escapes first so the
        // raw LLM text can't inject tags.
        bubbleHTML += `<div class="ai-markdown">${_renderSimpleMarkdown(prose)}</div>`;
    }
    if (options.length > 0) {
        bubbleHTML += '<div class="option-buttons">';
        for (const opt of options) {
            bubbleHTML += `<button class="option-btn" data-value="${opt.num}" title="Send: ${opt.num}">`
                       + `<span class="option-num">${opt.num}</span> ${opt.label}</button>`;
        }
        bubbleHTML += '</div>';
    }

    msg.innerHTML = `
        <div class="avatar-small" style="${_getActiveWizardAvatarStyle()}"></div>
        <div class="bubble">${bubbleHTML}</div>
    `;

    // Wire button clicks to auto-send the number
    msg.querySelectorAll('.option-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const val = btn.dataset.value;
            addUserMessage(val);
            // Disable all option buttons in this message (already picked)
            msg.querySelectorAll('.option-btn').forEach(b => {
                b.disabled = true;
                b.classList.add('used');
            });
            btn.classList.add('selected');
            askKobold(val);
        });
    });

    chatStream.appendChild(msg);
    chatStream.scrollTop = chatStream.scrollHeight;
    _messageEntrance(msg);
    if (!opts.skipPersist) {
        _persistChatRecord({ role: 'assistant', content: text, ts: Date.now() / 1000 });
    }
    // Return the .bubble element so callers (e.g. SpellcasterActions)
    // can append action buttons scoped to this message.
    return msg.querySelector('.bubble') || msg;
}

function addUserMessage(text, opts = {}) {
    const msg = document.createElement('div');
    msg.className = 'message user-message';
    // `text` is raw user chat input — MUST be escaped before landing
    // in innerHTML. USER_SPARKLE_SVG is a static in-file constant so
    // it's left as-is. `<br>` translation is applied on the escaped
    // text so \n still renders as a line break.
    msg.innerHTML = `
        <div class="avatar-small">${USER_SPARKLE_SVG}</div>
        <div class="bubble"><p>${_esc(text).replace(/\n/g, '<br>')}</p></div>
    `;
    // Starter chips are only for the cold-start. Any user message kills them.
    const starter = chatStream.querySelector('.starter-chips');
    if (starter) starter.remove();
    chatStream.appendChild(msg);
    chatStream.scrollTop = chatStream.scrollHeight;
    _messageEntrance(msg);
    if (!opts.skipPersist) {
        _persistChatRecord({ role: 'user', content: text, ts: Date.now() / 1000 });
    }
}

function addSystemMessage(htmlContent, opts = {}) {
    const msg = document.createElement('div');
    msg.className = 'message ai-message';
    msg.innerHTML = `
        <div class="avatar-small comfyui-logo">${COMFYUI_LOGO_SVG}</div>
        <div class="bubble system-bubble"><p>${htmlContent}</p></div>
    `;
    chatStream.appendChild(msg);
    chatStream.scrollTop = chatStream.scrollHeight;
    _messageEntrance(msg);
    if (!opts.skipPersist) {
        _persistChatRecord({ role: 'system', content: htmlContent, ts: Date.now() / 1000 });
    }
}

// ─── Generation bubble + recast button ──────────────────────────────
//
// Renders a "Spell Complete!" bubble for one or more generated images
// or videos and attaches a "Cast Again" button that re-fires the
// saved spell payload. The payload is embedded in a data attribute so
// the button still works after a refresh+replay (the closure is gone
// but the JSON survives in the DOM).
function addGenerationMessage(payload, mediaType, urls, opts = {}) {
    if (!Array.isArray(urls)) urls = [];
    const msg = document.createElement('div');
    msg.className = 'message ai-message';

    let mediaHtml = '';
    if (mediaType === 'images') {
        mediaHtml = urls.map(u =>
            `<img src="${u}" class="generated-image" style="max-width:100%;border-radius:8px;margin:4px 0;">`
        ).join('');
    } else if (mediaType === 'videos') {
        mediaHtml = urls.map(u =>
            `<video src="${u}" controls autoplay loop muted style="max-width:100%;border-radius:8px;margin:4px 0;"></video>`
        ).join('');
    }

    // Recast button — only renders if we actually have a payload to
    // re-fire. Direct casts and historical replays both qualify.
    let recastBtnHtml = '';
    if (payload && (payload.build_fn || payload.node)) {
        // Embed the payload as a base64-encoded JSON blob on the button
        // so the click handler can recover it after a page refresh.
        const encoded = btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
        recastBtnHtml = `
            <div class="recast-row" style="margin-top:8px;display:flex;gap:6px;align-items:center;">
                <button class="recast-btn" data-payload="${encoded}"
                    title="Cast this spell again, optionally in a batch"
                    style="padding:4px 12px;background:linear-gradient(135deg,rgba(178,70,242,0.2),rgba(252,211,77,0.2));border:1px solid rgba(252,211,77,0.4);border-radius:6px;color:#fde68a;font-size:11px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:4px;">
                    \u2728 Cast Again
                </button>
            </div>
        `;
    }

    // Image action chips — universal next-step actions below every
    // generated image. Clicking either switches to another wizard
    // (with the image attached as context) or stays and fires a
    // canned message. Only rendered for image outputs; videos skip.
    //
    // Cross-interface chips (targetInterface set) are filtered here
    // so a "Send to Resolve" chip never appears when Resolve isn't
    // installed + online. No dead functions in the UI.
    let imageActionsHtml = '';
    if (mediaType === 'images' && urls.length > 0 && typeof window.getImageActionChips === 'function') {
        const actions = window.getImageActionChips().filter(a => {
            if (!a.targetInterface) return true;  // guild-internal chips always show
            return typeof window.isInterfaceActive === 'function'
                && window.isInterfaceActive(a.targetInterface);
        });
        const firstUrl = urls[0];
        imageActionsHtml = '<div class="image-action-chips" data-img-url="' + firstUrl + '">' +
            actions.map((a, i) =>
                `<button class="option-btn image-action-chip" data-idx="${i}" title="${a.label}">` +
                `<span class="chip-icon">${a.icon}</span><span class="chip-label">${a.label}</span></button>`
            ).join('') +
            `<button class="option-btn image-action-chip image-action-more" data-more="1" title="More actions">` +
            `<span class="chip-icon">\u22ef</span><span class="chip-label">More</span></button>` +
            '</div>';
    }

    msg.innerHTML = `
        <div class="avatar-small comfyui-logo">${COMFYUI_LOGO_SVG}</div>
        <div class="bubble system-bubble">
            <p><strong>Spell Complete!</strong></p>
            ${mediaHtml}
            ${recastBtnHtml}
            ${imageActionsHtml}
        </div>
    `;

    // Wire the recast button — opens the inline batch form below the bubble.
    const rb = msg.querySelector('.recast-btn');
    if (rb) {
        rb.addEventListener('click', () => {
            try {
                const json = decodeURIComponent(escape(atob(rb.dataset.payload)));
                const restored = JSON.parse(json);
                _openRecastFlow(restored);
            } catch (e) {
                addSystemMessage('<em>Could not recover the saved spell payload.</em>');
            }
        });
    }

    // 👍 / 👎 per generated image. Meta fields let the backend bless the
    // settings into CalibrationProfile on +1, so the user's taste compounds
    // without them ever having to open a settings panel.
    if (typeof window.SpellcasterFeedback !== 'undefined'
        && mediaType === 'images' && urls.length > 0) {
        const imgs = msg.querySelectorAll('img.generated-image');
        imgs.forEach((img, i) => {
            const subjectId = urls[i] || img.src;
            const params = (payload && payload.params) || {};
            const preset = params.preset || {};
            const meta = {
                model:     preset.ckpt || preset.unet || params.model || '',
                arch:      preset.arch || '',
                cfg:       preset.cfg,
                steps:     preset.steps,
                sampler:   preset.sampler,
                scheduler: preset.scheduler,
                denoise:   preset.denoise,
                width:     preset.width,
                height:    preset.height,
                seed:      params.seed,
                prompt:    params.prompt || params.prompt_text || '',
                negative:  params.negative_prompt || params.negative_text || '',
                build_fn:  (payload && payload.build_fn) || '',
            };
            window.SpellcasterFeedback.attach(img, 'chat_gen', subjectId, meta);
        });
    }

    // Wire image action chips — switch wizard (if needed) + attach image + send canned message
    const actionStrip = msg.querySelector('.image-action-chips');
    if (actionStrip) {
        const imgUrl = actionStrip.dataset.imgUrl;
        actionStrip.querySelectorAll('.image-action-chip').forEach(btn => {
            btn.addEventListener('click', (ev) => {
                ev.preventDefault();
                if (btn.dataset.more === '1') {
                    _showImageActionOverflow(btn, imgUrl);
                    return;
                }
                const idx = parseInt(btn.dataset.idx, 10);
                // Same filter as the renderer so indices line up with
                // the chips that were actually displayed
                const actions = window.getImageActionChips().filter(a => {
                    if (!a.targetInterface) return true;
                    return typeof window.isInterfaceActive === 'function'
                        && window.isInterfaceActive(a.targetInterface);
                });
                const action = actions[idx];
                if (!action) return;
                _dispatchImageAction(action, imgUrl);
            });
        });
    }

    chatStream.appendChild(msg);
    chatStream.scrollTop = chatStream.scrollHeight;
    _messageEntrance(msg);
    if (!opts.skipPersist) {
        _persistChatRecord({
            role: 'generation',
            payload: payload || null,
            type: mediaType || 'images',
            urls: urls,
            ts: Date.now() / 1000,
        });
    }
}

// Dispatch an image-action chip click.
// If the action targets another wizard, stash the image URL + message
// in a global, switch to that wizard (which will render an attachment
// bubble + fire the canned message via _renderPendingAttachment).
// If targetWizard is null, fire the message on the current wizard.
// Special case: message === "__DOWNLOAD__" triggers a download.
function _dispatchImageAction(action, imageUrl) {
    if (!action) return;
    if (action.message === "__DOWNLOAD__") {
        // Save-to-disk: open the image in a new tab with download hint
        const a = document.createElement('a');
        a.href = imageUrl;
        a.download = imageUrl.split('/').pop().split('?')[0] || 'spellcaster_image.png';
        a.target = '_blank';
        document.body.appendChild(a);
        a.click();
        a.remove();
        return;
    }

    // Cross-interface chip: persist the image to the shared gallery
    // (so the URL is stable across privacy cleanup) then fire a bus
    // event the external plugin subscribes to. Plugin does whatever's
    // appropriate on its side (import into media pool, open in editor).
    // We only render a confirmation bubble in chat — no wizard switch.
    if (action.targetInterface) {
        const absUrl = (imageUrl && imageUrl.startsWith('http'))
            ? imageUrl
            : new URL(imageUrl, window.location.origin).href;
        const kind = action.actionKind || `${action.targetInterface}.asset.send`;
        addSystemMessage(`<em>${action.icon} ${action.message}</em>`);
        // Fire-and-forget async: persist → emit. If the gallery is
        // disabled or the source URL is unreachable, fall back to
        // emitting with the raw URL.
        _persistAndEmitAsset(absUrl, kind, action);
        return;
    }

    // Fire on current wizard — just send the canned message inline
    if (!action.targetWizard || action.targetWizard === activeCharacterId) {
        addUserMessage(action.label);
        askKobold(`${action.message}\n\n[The user is referring to this image: ${imageUrl}]`);
        return;
    }

    // Cross-wizard: stash context, switch, and let selectCharacter render
    // the attachment bubble + fire the canned message once history loads.
    window._pendingImageContext = {
        imageUrl: imageUrl,
        message: action.message,
    };
    selectCharacter(action.targetWizard);
}

// Persist an image URL to the shared gallery, then emit a bus event
// so the target interface receives both a stable hash URL AND the
// original reference. External plugins can use whichever they prefer.
async function _persistAndEmitAsset(imageUrl, kind, action) {
    let assetHash = null;
    let galleryUrl = null;
    try {
        // Pull the bytes (same-origin, should be fast)
        const resp = await fetch(imageUrl);
        if (resp.ok) {
            const blob = await resp.blob();
            const b64 = await _blobToBase64(blob);
            const uploadResp = await fetch('/api/assets', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    origin: 'guild',
                    kind: 'send_to_' + (action.targetInterface || 'other'),
                    title: action.label || '',
                    prompt: action.message || '',
                    body_b64: b64,
                    meta: {source_url: imageUrl},
                }),
            });
            if (uploadResp.ok) {
                const rec = await uploadResp.json();
                assetHash = rec.hash;
                galleryUrl = window.location.origin + '/api/assets/' + rec.hash;
            }
        }
    } catch (e) { /* fall through — emit without gallery */ }

    // Emit the event whether or not the upload succeeded
    fetch('/api/events/emit', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            kind: kind,
            origin: 'guild',
            data: {
                image_url: galleryUrl || imageUrl,  // prefer stable URL
                source_url: imageUrl,
                asset_hash: assetHash,
                source: 'image-action-chip',
                chip_label: action.label || '',
            },
        }),
    }).catch(() => {/* silent */});
}

function _blobToBase64(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
            // result looks like "data:image/png;base64,iVBORw0KGgo..."
            const s = reader.result || '';
            const comma = s.indexOf(',');
            resolve(comma >= 0 ? s.substring(comma + 1) : s);
        };
        reader.onerror = reject;
        reader.readAsDataURL(blob);
    });
}

// Show the overflow menu for extra image actions.
function _showImageActionOverflow(anchorBtn, imageUrl) {
    if (typeof window.getImageActionOverflow !== 'function') return;
    // Remove any existing overflow popover
    document.querySelectorAll('.image-action-overflow').forEach(el => el.remove());

    // Same interface-gating as the primary chips: an overflow entry
    // that targets an absent interface stays out of the menu
    const overflow = window.getImageActionOverflow().filter(a => {
        if (!a.targetInterface) return true;
        return typeof window.isInterfaceActive === 'function'
            && window.isInterfaceActive(a.targetInterface);
    });
    const pop = document.createElement('div');
    pop.className = 'image-action-overflow';
    overflow.forEach((a, i) => {
        const item = document.createElement('button');
        item.className = 'option-btn image-action-chip image-action-overflow-item';
        item.innerHTML = `<span class="chip-icon">${a.icon}</span><span class="chip-label">${a.label}</span>`;
        item.addEventListener('click', (ev) => {
            ev.stopPropagation();
            pop.remove();
            _dispatchImageAction(a, imageUrl);
        });
        pop.appendChild(item);
    });
    // Position below the "More" button
    anchorBtn.parentElement.appendChild(pop);

    // Dismiss on outside click
    const dismiss = (ev) => {
        if (!pop.contains(ev.target) && ev.target !== anchorBtn) {
            pop.remove();
            document.removeEventListener('click', dismiss, true);
        }
    };
    setTimeout(() => document.addEventListener('click', dismiss, true), 0);
}

// Open the Archivist's recast prompt with an inline N-times batch form.
// Triggered by clicking a "Cast Again" button on any past generation.
function _openRecastFlow(payload) {
    const archivistText = "I see that you are interested in this spell. Would you like me to cast it again? If so, how many times?";
    addAIMessage(archivistText);

    // Inline form: number input + Cast button. Persisted as a system
    // message so a refresh shows the user the form they had open.
    const formMsg = document.createElement('div');
    formMsg.className = 'message ai-message';
    formMsg.innerHTML = `
        <div class="avatar-small comfyui-logo">${COMFYUI_LOGO_SVG}</div>
        <div class="bubble system-bubble">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                <label style="font-size:12px;color:#fde68a;">How many times?</label>
                <input type="number" min="1" max="20" value="1"
                    class="recast-count"
                    style="width:60px;padding:4px 8px;border-radius:6px;border:1px solid rgba(252,211,77,0.4);background:#1a1a2e;color:#eee;font-size:13px;text-align:center;">
                <button class="recast-go"
                    style="padding:5px 14px;background:linear-gradient(135deg,#B246F2,#f59e0b);border:none;border-radius:6px;color:#fff;font-size:12px;font-weight:600;cursor:pointer;">
                    Cast
                </button>
                <button class="recast-cancel"
                    style="padding:5px 12px;background:transparent;border:1px solid #444;border-radius:6px;color:#888;font-size:11px;cursor:pointer;">
                    Cancel
                </button>
            </div>
        </div>
    `;
    chatStream.appendChild(formMsg);
    chatStream.scrollTop = chatStream.scrollHeight;
    _messageEntrance(formMsg);

    const countInput = formMsg.querySelector('.recast-count');
    const goBtn = formMsg.querySelector('.recast-go');
    const cancelBtn = formMsg.querySelector('.recast-cancel');

    cancelBtn.addEventListener('click', () => {
        formMsg.remove();
    });

    goBtn.addEventListener('click', async () => {
        let n = parseInt(countInput.value, 10);
        if (!Number.isFinite(n) || n < 1) n = 1;
        if (n > 20) n = 20;
        // Remove the form so it can't be double-submitted
        formMsg.remove();
        addUserMessage(n === 1 ? 'Cast it again.' : `Cast it ${n} times.`);
        // Sequential dispatch — one at a time so each result lands in
        // the chat as it completes. Direct casts route to a different
        // endpoint than studio build_fn dispatches.
        for (let i = 0; i < n; i++) {
            const fresh = JSON.parse(JSON.stringify(payload));
            if (fresh.params && typeof fresh.params === 'object'
                && fresh.params.seed !== undefined) {
                fresh.params.seed = Math.floor(Math.random() * 1000000000);
            }
            // eslint-disable-next-line no-await-in-loop
            if (fresh.build_fn === 'direct_cast') {
                await _recastDirect(fresh);
            } else {
                await dispatchToComfy(fresh);
            }
        }
    });
}

// Re-fire a direct-cast snapshot through /api/direct_cast and render
// the result via addGenerationMessage so the new bubble also gets a
// recast button (and gets persisted to the chat log).
async function _recastDirect(snapshot) {
    const promptText = (snapshot && snapshot.params && snapshot.params.prompt) || '';
    if (!promptText) {
        addSystemMessage('<em>Direct cast snapshot missing prompt.</em>');
        return;
    }
    try {
        const r = await fetch('/api/direct_cast', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                char_id: activeCharacterId,
                prompt: promptText,
                comfy_url: comfyUrl,
            }),
        });
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            addSystemMessage(`<strong>Spell Failed!</strong><br>${err.error || ('HTTP ' + r.status)}`);
            return;
        }
        const data = await r.json();
        if (data.type === 'images' && data.urls && data.urls.length) {
            addGenerationMessage(snapshot, 'images', data.urls);
        } else if (data.type === 'videos' && data.urls && data.urls.length) {
            addGenerationMessage(snapshot, 'videos', data.urls);
        } else {
            addSystemMessage(`<strong>Spell Complete!</strong>`);
        }
    } catch (e) {
        addSystemMessage(`<strong>Spell Failed!</strong><br>${e.message}`);
    }
}

// Client-side mirror of server's _is_direct_generation_prompt heuristic.
// Used as a cheap pre-check; the server still validates before bypassing.
function _looksLikeDirectGenPrompt(text) {
    if (!text) return false;
    const t = text.trim();
    if (!t || t.length > 240) return false;
    if (t.indexOf('?') !== -1) return false;
    if ((t.match(/\./g) || []).length >= 2) return false;
    const low = t.toLowerCase();
    const chatMarkers = [
        'what ', 'who ', 'why ', 'how ', 'when ', 'where ', 'which ',
        'can you', 'could you', 'would you', 'do you', 'are you',
        'tell me about', 'explain', 'help me understand', 'list ',
        'hello', 'hi ', 'hey ', 'thanks', 'thank you',
    ];
    for (const m of chatMarkers) {
        if (low.startsWith(m) || low.indexOf(' ' + m) !== -1) return false;
    }
    const genVerbs = [
        'generate', 'make ', 'create', 'render', 'cast ', 'draw ',
        'paint ', 'show me', 'conjure', 'summon', 'produce',
        'imagine', 'picture ', 'give me', 'i want a picture',
        'i want an image', 'i want a photo', 'make me a', 'make me an',
        'a photo of', 'a picture of', 'an image of', 'a portrait of',
        'a painting of', 'a scene of', 'a scene with',
    ];
    if (genVerbs.some(v => low.indexOf(v) !== -1)) return true;
    const wc = t.split(/\s+/).length;
    if (wc >= 2 && wc <= 30 && low.indexOf(':') === -1 && low.indexOf(';') === -1) {
        return true;
    }
    return false;
}

// Find every plausible JSON-shaped block in an LLM reply and return
// (a) the parsed spell payload to dispatch, if any, and (b) the
// remaining text with ALL JSON-shaped blocks stripped — even ones
// we couldn't parse, so the user never sees raw JSON leak through.
//
// Returns: { payload: object|null, displayText: string }
function _extractSpellPayload(reply) {
    if (!reply) return { payload: null, displayText: "" };
    let working = reply;
    let payload = null;

    // 1. Find all fenced code blocks. Tries CLOSED fences first
    //    (```json ... ```), then UNCLOSED ones (```json ... <eof>) so
    //    truncated LLM output still gets caught.
    const fencedRanges = [];   // [{full, inner, start, end}]
    const closedFenceRegex = /```(?:json)?\s*([\s\S]*?)\s*```/gi;
    let m;
    while ((m = closedFenceRegex.exec(reply)) !== null) {
        fencedRanges.push({
            full: m[0], inner: m[1], start: m.index, end: m.index + m[0].length,
        });
    }
    // Unclosed fence: a ```json (or ```) with no closing fence after it.
    // Capture from the opener to end-of-string.
    const unclosedFenceRegex = /```(?:json)?\s*([\s\S]*)$/gi;
    while ((m = unclosedFenceRegex.exec(reply)) !== null) {
        const span = { start: m.index, end: m.index + m[0].length };
        // Skip if this is already covered by a closed fence
        if (fencedRanges.some(r => span.start >= r.start && span.start < r.end)) continue;
        fencedRanges.push({
            full: m[0], inner: m[1], start: span.start, end: span.end,
        });
    }

    // 2. Find any bare {...} blocks that LOOK like a spell payload, even
    //    if not fenced. Accepts both double-quoted ("build_fn") and
    //    single-quoted ('build_fn') variants because dumb LLMs drop into
    //    Python dict syntax all the time.
    const bareRanges = [];
    {
        for (let i = 0; i < reply.length; i++) {
            if (reply[i] !== '{') continue;
            // Skip if this { is inside a fenced range we already captured
            if (fencedRanges.some(r => i >= r.start && i < r.end)) continue;
            let depth = 0;
            let end = -1;
            let inStr = false;
            let strCh = '';
            let escape = false;
            for (let j = i; j < reply.length; j++) {
                const c = reply[j];
                if (escape) { escape = false; continue; }
                if (c === '\\') { escape = true; continue; }
                if (inStr) {
                    if (c === strCh) inStr = false;
                    continue;
                }
                if (c === '"' || c === "'") { inStr = true; strCh = c; continue; }
                if (c === '{') depth++;
                else if (c === '}') {
                    depth--;
                    if (depth === 0) { end = j + 1; break; }
                }
            }
            // Truncated case: opening { but no balanced closing }. If it
            // contains spell markers, take it as a candidate from i to EOS.
            if (end === -1) {
                const tail = reply.substring(i);
                if (/["']build_fn["']|["']node["']/.test(tail)) {
                    bareRanges.push({
                        full: tail, inner: tail, start: i, end: reply.length,
                    });
                }
                break;
            }
            const block = reply.substring(i, end);
            if (/["']build_fn["']|["']node["']/.test(block)) {
                bareRanges.push({ full: block, inner: block, start: i, end });
                i = end - 1;  // skip past this block
            }
        }
    }

    // 3. Try each candidate (fenced first, then bare) until one parses.
    const tryParse = (raw) => {
        // Common LLM screwups we can repair:
        //  - Python dict syntax: single quotes -> double quotes
        //  - Trailing comma before closing brace/bracket
        //  - Smart quotes
        //  - Truncated: balance braces if open > close
        let s = raw.trim();
        // Strip any leading "json" word the LLM left in
        s = s.replace(/^json\s*/i, '');
        // Smart quotes -> ASCII
        s = s.replace(/[\u201C\u201D]/g, '"').replace(/[\u2018\u2019]/g, "'");
        // First pass: as-is
        try { return JSON.parse(s); } catch (e) {}
        // Repair: single-quote keys/values to double-quote
        // (only if there are no unescaped double-quotes inside, which would conflict)
        let repaired = s;
        if (!/("[^"]*")/.test(repaired) || /'[^']*'/.test(repaired)) {
            repaired = repaired.replace(/'([^'\\]*(?:\\.[^'\\]*)*)'/g, '"$1"');
        }
        // Repair: trailing commas
        repaired = repaired.replace(/,(\s*[}\]])/g, '$1');
        // Repair: balance braces if open > close
        const opens = (repaired.match(/\{/g) || []).length;
        const closes = (repaired.match(/\}/g) || []).length;
        if (opens > closes) repaired += '}'.repeat(opens - closes);
        try { return JSON.parse(repaired); } catch (e) {}
        return null;
    };

    for (const r of [...fencedRanges, ...bareRanges]) {
        const parsed = tryParse(r.inner);
        if (parsed && (parsed.build_fn || parsed.node)) {
            payload = parsed;
            break;
        }
    }

    // Telemetry: if we found one or more spell-marker bare blocks but
    // none of them parsed, log the first fragment so we can fix the LLM
    // output shape before users hit it. Fire-and-forget — never blocks.
    // bareRanges only contain blocks that already matched build_fn/node
    // markers, so any entry here is a confirmed near-miss.
    if (!payload && bareRanges.length > 0) {
        try {
            fetch('/api/telemetry/parse_miss', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    fragment: String(bareRanges[0].full).substring(0, 500),
                    ts: Date.now() / 1000,
                }),
                keepalive: true,
            }).catch(() => {});
        } catch (e) { /* ignore */ }
    }

    // 4. Sanitize the displayText: strip ALL fenced blocks AND all bare
    //    JSON-looking blocks, parsed or not. This guarantees no leak even
    //    when parsing fails — the user sees the LLM's prose only.
    let displayText = reply;
    // Sort by start position descending so substring removals don't shift
    // earlier indices.
    const allRanges = [...fencedRanges, ...bareRanges].sort((a, b) => b.start - a.start);
    for (const r of allRanges) {
        displayText = displayText.substring(0, r.start) + displayText.substring(r.end);
    }
    // Collapse the whitespace damage from cut-out blocks
    displayText = displayText.replace(/\n{3,}/g, '\n\n').trim();
    // Strip common LLM throat-clearing prefixes that cling to the now-empty
    // intro: "Sure!", "Here's the JSON:", "Here you go:", "Let me cast it:"
    displayText = displayText.replace(
        /^\s*(sure[!.,]?|okay[!.,]?|ok[!.,]?|here(?:'s| is| you go)[^.\n]{0,40}[:.]?|let me [^.\n]{0,40}[:.]?|alright[!.,]?)\s*/i,
        ''
    ).trim();

    return { payload, displayText };
}

// Expand a bare "1" / "3." / "option 2" into "1 (Text-to-Image)" by
// reading the most recent assistant message and finding the matching
// numbered-list item. Small LLMs (OpenHermes 7B et al.) can't always
// correlate a digit with the menu they just emitted; prepending the
// label removes the guesswork. Returns the original string if no
// numbered item matches — never more disruptive than a no-op.
function _expandNumericShortcut(userText) {
    const m = (userText || '').trim().match(/^(?:option\s*)?(\d+)\.?\)?$/i);
    if (!m) return userText;
    const n = parseInt(m[1], 10);
    if (!n || n > 50) return userText;
    for (let i = chatHistory.length - 1; i >= 0; i--) {
        const h = chatHistory[i];
        if (h.role !== 'assistant') continue;
        const content = h.content || '';
        const lineRe = new RegExp(
            '(?:^|\\n)\\s*' + n +
            '[.)]\\s+(?:\\*\\*([^*\\n]+)\\*\\*|([^\\n]{3,120}))', 'm');
        const lm = content.match(lineRe);
        if (!lm) break;
        let label = (lm[1] || lm[2] || '').trim();
        // Strip trailing em-dash descriptions and markdown emphasis
        label = label.split(/\s+[—–-]\s+/)[0].replace(/[*_]/g, '').trim();
        if (!label) break;
        return `${n} (${label})`;
    }
    return userText;
}

async function askKobold(text) {
    sendBtn.disabled = true;
    addTypingIndicator();
    try {
        const char = characters.find(c => c.id === activeCharacterId);
        if (!char) {
            addSystemMessage("<strong>Summon Status:</strong> No active wizard selected. Please select one from the sidebar first.");
            return;
        }

        // Rewrite bare-number replies to (1 (Text-to-Image)) so the LLM
        // has enough context to advance the scaffold — see
        // _expandNumericShortcut above.
        text = _expandNumericShortcut(text);

        // Add the current user turn to the in-memory history. This used
        // to be missing entirely — chatHistory held only assistant
        // records in-session, so the prompt below built from it ended
        // with "Assistant: " and the LLM had to hallucinate the user's
        // message. That's why single-digit replies looped: the model
        // literally never saw "1".
        chatHistory.push({ role: 'user', content: text });

        // Direct-cast bypass: if the user clearly typed an image-gen prompt,
        // skip the LLM round-trip entirely. The LLM can't be trusted to emit
        // a JSON block reliably, so we hand the prompt straight to ComfyUI.
        // Server returns 409 if the wizard doesn't support direct casting,
        // in which case we fall through to the normal LLM path.
        if (_looksLikeDirectGenPrompt(text)) {
            try {
                const dcRes = await fetch('/api/direct_cast', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        char_id: activeCharacterId,
                        prompt: text,
                        comfy_url: comfyUrl,
                    }),
                });
                if (dcRes.ok) {
                    const dcData = await dcRes.json();
                    chatHistory.push({ role: 'assistant', content: '[direct cast]' });
                    // Direct casts re-fire through the same code path
                    // as LLM-routed dispatches: build a synthetic
                    // payload with build_fn=direct_cast + the prompt
                    // text so the recast button has something to
                    // re-submit. The server accepts this shape via a
                    // fall-through in /api/direct_cast.
                    const dcSnapshot = {
                        build_fn: 'direct_cast',
                        params: { prompt: text },
                    };
                    if (dcData.type === 'images' && dcData.urls && dcData.urls.length) {
                        addGenerationMessage(dcSnapshot, 'images', dcData.urls);
                    } else if (dcData.type === 'videos' && dcData.urls && dcData.urls.length) {
                        addGenerationMessage(dcSnapshot, 'videos', dcData.urls);
                    } else {
                        addSystemMessage(`<strong>Spell Complete!</strong>`);
                    }
                    return;
                }
                // 409 = wizard not eligible for direct cast → fall through to LLM
            } catch (e) {
                console.warn('direct_cast failed, falling back to LLM:', e);
            }
        }

        // Fetch per-character system prompt if available, else use global
        let charPrompt = systemPrompt;
        try {
            const cpRes = await fetch(`/api/system_prompt/${char.id}`);
            const cpData = await cpRes.json();
            if (cpData.prompt) charPrompt = cpData.prompt;
        } catch(e) { /* fallback to global */ }

        // Build the mega prompt
        let context = `${charPrompt}\n\nYour Persona:\nYou are ${char.name}, a magical expert in ${char.subtext}.\n${char.personality || ''}\n\n`;
        for(let h of chatHistory) {
            context += `${h.role === 'user' ? 'User' : 'Assistant'}: ${h.content}\n`;
        }
        context += "Assistant: ";

        // Warn in chat on first horde message per session
        if (llmMode === 'horde' && !window._hordeWarnShown) {
            addSystemMessage(
                '\u26a0 <strong>Horde Mode Active</strong> — Your message is being sent to ' +
                'volunteer workers on the AI Horde network. <strong>Do not share personal or sensitive info.</strong>'
            );
            window._hordeWarnShown = true;
        }

        // Nudge the LLM to output JSON if the user prompt looks like a gen request.
        //
        // Two hard gates stop the nudge from firing on conversations:
        //   1. The active wizard must actually be able to dispatch a build_fn —
        //      onboarding / install-manager wizards have an empty build_fns list
        //      and should NEVER receive a JSON-only instruction. Without this
        //      gate, every chat turn with the Spellcaster wizard got redirected
        //      into image generation.
        //   2. The message must not look like a question. "How do I make a
        //      picture?" contains "make" and "picture" (both direct keywords)
        //      but it's a help request, not a gen request. Question markers
        //      unambiguously signal conversation.
        let activePrompt = context;
        const canDispatch = Array.isArray(char.build_fns) && char.build_fns.length > 0;
        const low = text.toLowerCase();
        const questionMarkers = ['?', 'how do', 'how can', 'how to', 'what is', 'what are',
            'why ', 'when ', 'where ', 'who ', 'help', 'explain', 'guide me', 'walk me'];
        const isQuestion = questionMarkers.some(m => low.includes(m));
        const directKeywords = ['generate', 'make', 'create', 'render', 'cast', 'show me', 'conjure',
            'draw', 'paint', 'picture', 'image', 'photo', 'portrait', 'scene'];
        const isDirect = text.length < 200 && !isQuestion && directKeywords.some(k => low.includes(k));
        const isDescriptive = text.length < 200 && !isQuestion && text.split(/\s+/).length >= 3;
        if (canDispatch && (isDirect || isDescriptive) && !context.includes('```json')) {
            activePrompt += `(IMPORTANT: The user wants you to generate an image. Do NOT describe what you would create. Do NOT rephrase their request. Output ONLY the JSON block now. Example format:
\`\`\`json
{"build_fn": "build_txt2img", "params": {"prompt": "the actual SDXL/Flux prompt here"}}
\`\`\`
Output the JSON block immediately — no preamble, no explanation.)
Assistant: \`\`\`json
`;
        }

        const data = await llmGenerate({
            prompt: activePrompt,
            max_context_length: 4096,
            max_length: 800,
            temperature: 0.7,
            rep_pen: 1.15,
            rep_pen_range: 512,
            stop_sequence: ["User:", "\nUser"]
        });
        let aiReply = data.results[0].text.trim();

        chatHistory.push({ role: 'assistant', content: aiReply });

        // ── <ACTION> block extraction (Spellcaster scaffold) ──
        //
        // The onboarding scaffold instructs the LLM to emit action
        // requests as <ACTION>{...}</ACTION>. We peel those off first
        // and render them as clickable buttons under the message so the
        // user doesn't have to type "yes" to every suggestion. The raw
        // tag is stripped from the displayed text.
        let scaffoldActions = [];
        if (typeof window.SpellcasterActions !== 'undefined') {
            const parsed = window.SpellcasterActions.parseActions(aiReply);
            if (parsed.actions.length) {
                aiReply = parsed.cleanText;
                scaffoldActions = parsed.actions;
            }
        }

        // ── Robust JSON extraction + leak-proof rendering ──
        //
        // The dumb local LLM emits JSON in many shapes: fenced, unfenced,
        // partially fenced, prefixed with chatter, with python-dict
        // syntax, broken across lines, etc. Our job:
        //   1. Find any plausible JSON payload (a build_fn dispatch).
        //   2. Try to dispatch it.
        //   3. NEVER leave raw JSON visible to the user — even if parsing
        //      fails, strip JSON-shaped blocks from the displayed text.
        //
        // _extractSpellPayload returns { payload, displayText }:
        //   payload     — parsed object (or null if no spell could be dispatched)
        //   displayText — sanitized chat body with all JSON-looking blocks removed
        const result = _extractSpellPayload(aiReply);
        let displayedEl = null;
        if (result.payload) {
            if (result.displayText) displayedEl = addAIMessage(result.displayText);
            addSystemMessage(`<strong>Spell Succeeded!</strong><br>Executing JSON Workflow payload...`);
            dispatchToComfy(result.payload);
        } else if (result.displayText) {
            displayedEl = addAIMessage(result.displayText);
        } else if (scaffoldActions.length) {
            // All content was ACTION blocks — render just the buttons with
            // a minimal placeholder message so the user sees something.
            displayedEl = addAIMessage('<em>Ready when you are.</em>');
        } else {
            // Empty reply OR JSON-shaped reply that we stripped but couldn't
            // parse. Don't leak the raw output — tell the user to try again.
            addSystemMessage("<em>The wizard's reply was unclear or malformed. Try rephrasing your request.</em>");
        }

        // Append action buttons under whichever message element we just rendered
        if (scaffoldActions.length && displayedEl
            && typeof window.SpellcasterActions !== 'undefined') {
            window.SpellcasterActions.renderActionButtons(displayedEl, scaffoldActions);
        }

    } catch (err) {
        addAIMessage(`[Error: Could not connect to LLM at ${koboldUrl}. Click Settings to configure.]`);
        console.error(err);
    } finally {
        removeTypingIndicator();
        sendBtn.disabled = false;
    }
}

async function dispatchToComfy(payload) {
    try {
        payload.comfy_url = comfyUrl; // Intercept and attach user's Comfy URL natively
        payload.char_id = activeCharacterId; // Tell the server which wizard is requesting
        // Telemetry: log the dispatch shape (no prompt content). Fire-and-
        // forget so it never blocks the actual /api/execute call.
        try {
            fetch('/api/telemetry/dispatch_ok', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    build_fn: String(payload.build_fn || payload.node || ''),
                    char_id: String(activeCharacterId || ''),
                    ts: Date.now() / 1000,
                }),
                keepalive: true,
            }).catch(() => {});
        } catch (e) { /* ignore */ }
        const response = await fetch('/api/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json();

        if (!response.ok) {
            addSystemMessage(`<strong>Spell Failed!</strong><br>${data.error || 'Unknown server error (HTTP ' + response.status + ')'}`);
            return;
        }
        // Snapshot the spell payload (without the runtime fields the
        // server injected) so the recast button has something safe to
        // re-fire later. comfy_url and char_id are added back at
        // dispatch time, not stored.
        const snapshot = { ...payload };
        delete snapshot.comfy_url;
        delete snapshot.char_id;
        if (data.type === 'images' && data.urls && data.urls.length) {
            addGenerationMessage(snapshot, 'images', data.urls);
        } else if (data.type === 'videos' && data.urls && data.urls.length) {
            addGenerationMessage(snapshot, 'videos', data.urls);
        } else if (data.mock_img) {
            addGenerationMessage(snapshot, 'images', [data.mock_img]);
        } else {
            addSystemMessage(`<strong>Spell Complete!</strong><br>Result: ${JSON.stringify(data).substring(0, 200)}`);
        }
    } catch (e) {
        addSystemMessage(`<strong>Spell Failed!</strong><br>${e.message}`);
        console.error(e);
    }
}

// ── File attachment (📎 upload button) ──────────────────────────────
// Users click 📎, pick a local image, we POST it to /api/assets and
// stash the canonical /api/assets/<hash> URL as a pending attachment.
// The next send includes "[attached image: <url>]" so the LLM sees
// it (same pattern _renderPendingAttachment uses for cross-wizard
// hand-offs). One attachment in flight at a time — simpler UX and
// matches how the existing image-action chips work.
let _pendingAttachment = null;
let _pendingAttachmentBubble = null;

function _clearPendingAttachment() {
    _pendingAttachment = null;
    if (_pendingAttachmentBubble) {
        _pendingAttachmentBubble.remove();
        _pendingAttachmentBubble = null;
    }
}

function _renderPendingAttachmentPreview(imageUrl, fileName) {
    // Compact "staged" bubble above the input — not persisted, cleared
    // on send or manual × click. Using an inline preview next to the
    // input keeps the user oriented: the image IS attached, and the
    // next message will carry it.
    const wrap = document.createElement('div');
    wrap.className = 'pending-attachment';
    wrap.style.cssText =
        'display:flex;align-items:center;gap:10px;padding:6px 10px;' +
        'margin:0 0 6px;background:rgba(180,100,255,0.08);' +
        'border:1px solid rgba(180,100,255,0.25);border-radius:6px;' +
        'font-size:12px;color:#d0c0e8;';
    wrap.innerHTML =
        '<img src="' + imageUrl + '" style="width:32px;height:32px;' +
        'object-fit:cover;border-radius:4px;">' +
        '<span style="flex:1;opacity:0.9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">📎 ' +
        _esc(fileName || 'image') + '</span>' +
        '<button type="button" title="Remove attachment" ' +
        'style="background:transparent;border:0;color:#d0c0e8;cursor:pointer;font-size:14px;">×</button>';
    wrap.querySelector('button').addEventListener('click', _clearPendingAttachment);
    const inputArea = document.getElementById('chat-input-area');
    if (inputArea) inputArea.insertBefore(wrap, inputArea.firstChild);
    _pendingAttachmentBubble = wrap;
}

const uploadBtn = document.getElementById('upload-btn');
const uploadFileInput = document.getElementById('upload-file-input');
if (uploadBtn && uploadFileInput) {
    uploadBtn.addEventListener('click', () => {
        if (_pendingAttachment) {
            // Second click with an attachment already staged — treat as
            // "clear and pick a new one" so the user isn't stuck.
            _clearPendingAttachment();
        }
        uploadFileInput.value = '';
        uploadFileInput.click();
    });
    uploadFileInput.addEventListener('change', async () => {
        const file = uploadFileInput.files && uploadFileInput.files[0];
        if (!file) return;
        if (!file.type.startsWith('image/')) {
            addSystemMessage('<strong>Upload rejected:</strong> only images are supported here.');
            return;
        }
        if (file.size > 32 * 1024 * 1024) {
            addSystemMessage('<strong>Upload rejected:</strong> image is larger than 32 MB.');
            return;
        }
        try {
            const body_b64 = await _blobToBase64(file);
            const res = await fetch('/api/assets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    body_b64,
                    origin: 'guild',
                    kind: 'upload',
                    title: file.name,
                    meta: { source: 'chat_upload' },
                }),
            });
            const data = await res.json();
            if (!res.ok || !data.hash) {
                addSystemMessage('<strong>Upload failed:</strong> ' +
                    _esc(data.error || ('HTTP ' + res.status)));
                return;
            }
            const imageUrl = '/api/assets/' + data.hash;
            _pendingAttachment = { url: imageUrl, name: file.name };
            _renderPendingAttachmentPreview(imageUrl, file.name);
        } catch (e) {
            addSystemMessage('<strong>Upload failed:</strong> ' + _esc(e.message || String(e)));
        }
    });
}

sendBtn.addEventListener('click', () => {
    _spellCastFlash();
    const text = chatInput.value.trim();
    if (!text && !_pendingAttachment) return;

    // If an image is staged, render it as its own user bubble BEFORE
    // the text bubble so the chat log reads "image → question". Persist
    // the attachment reference alongside the message so a page reload
    // rehydrates the same visual history.
    const attach = _pendingAttachment;
    if (attach) {
        const attachMsg = document.createElement('div');
        attachMsg.className = 'message user-message';
        attachMsg.innerHTML =
            '<div class="avatar-small">' + USER_SPARKLE_SVG + '</div>' +
            '<div class="bubble">' +
            '<p style="font-size:12px;opacity:.8;margin:0 0 6px;">📎 ' +
            _esc(attach.name || 'attached image') + '</p>' +
            '<img src="' + attach.url + '" class="attachment-image" ' +
            'style="max-width:200px;border-radius:6px;display:block;">' +
            '</div>';
        chatStream.appendChild(attachMsg);
        _persistChatRecord({ role: 'user',
            content: '[attached image: ' + attach.url + ']',
            ts: Date.now() / 1000 });
    }

    const sendText = text || 'What can you tell me about this image?';
    addUserMessage(sendText);
    chatInput.value = '';
    chatInput.style.height = 'auto';

    if (attach) {
        askKobold(sendText + '\n\n[The user has attached this image: ' + attach.url + ']');
        _clearPendingAttachment();
    } else {
        askKobold(sendText);
    }
});

chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendBtn.click();
    }
});
chatInput.addEventListener('input', function() { this.style.height = 'auto'; this.style.height = (this.scrollHeight) + 'px'; });

resetBtn.addEventListener('click', () => {
    if (!activeCharacterId) return;
    // Clear the persistent server-side log first so the replay on
    // re-select doesn't immediately restore the messages we just
    // wiped from the DOM. Fire-and-forget; if the server is down the
    // local reset still happens.
    const charId = activeCharacterId;
    fetch('/api/chat_history/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ char_id: charId }),
    }).catch(() => {}).finally(() => {
        selectCharacter(charId);
    });
});

// ── Avatar Generate Modal (mirrors the bg modal layout) ─────────────
//
// Opens a small dropdown with SFW preset styles, NSFW preset styles
// (only visible on patched NSFW builds), and Custom (which prepopulates
// a best-guess prompt for the active wizard's model architecture so
// the user can edit before submitting).
const avatarModal = document.getElementById('avatar-modal');
const avatarStyleSelect = document.getElementById('avatar-style-select');
const avatarCustomPrompt = document.getElementById('avatar-custom-prompt');
const avatarNsfwGroup = document.getElementById('avatar-nsfw-group');

// Per-style prompt presets. Sent to the server as `style_prompt` along
// with the wizard ID — the server combines it with the wizard's archetype
// hint and generates the avatar through _dispatch_txt2img.
const _AVATAR_STYLE_PROMPTS = {
    sfw_default: "",  // empty = let the server use the default _build_avatar_prompt
    sfw_dramatic: "dramatic chiaroscuro portrait, intense gaze, deep shadows, single warm light source, painterly digital art, headshot composition, dark moody background",
    sfw_heroic: "heroic half-body portrait from below, towering perspective, dynamic pose, billowing cape, energy crackling from hands, rich fabric textures, ornate magical accessories, deep moody atmosphere, cinematic lighting, concept art style",
    sfw_painted: "renaissance-style oil painting portrait, chiaroscuro lighting, painterly brushwork, ornate background, dignified pose, classical composition, museum quality",
    sfw_anime: "anime-style half-body portrait, expressive eyes, cel-shaded, vibrant colors, dynamic composition, magical aura, fantasy character design",
    sfw_neutral: "studio portrait, clean neutral background, soft three-point lighting, sharp focus, professional headshot, magical attire visible, calm confident expression",
    nsfw_alluring: "sultry portrait, suggestive pose, warm bedroom lighting, half-lidded eyes, parted lips, sensual atmosphere, painterly digital art",
    nsfw_boudoir: "boudoir portrait, low intimate lighting, sheer fabrics, candlelight, sensual pose, painterly atmosphere, evocative mood",
    nsfw_revealing: "tasteful revealing portrait, sheer enchanted robes, glistening skin, soft warm light, romantic atmosphere, painterly art",
    nsfw_explicit: "explicit anatomical portrait, hardcore detail, raw sensuality, dramatic lighting, evocative pose, photorealistic",
};

function _avatarBestGuessPrompt(char) {
    // Fallback custom prompt — describes the active wizard's
    // architecture + specialty so the user has a template to edit.
    if (!char) return "";
    const arch = char.model_arch || "auto";
    const subtext = char.subtext || "magical specialist";
    return `portrait of a wizard named ${char.name || "the wizard"}, `
        + `${subtext}, magical aura, fantasy character design, painterly digital art, `
        + `expressive eyes, intricate magical attire, cinematic lighting`
        + (arch !== "auto" ? `, ${arch} architecture` : "");
}

generateAvatarBtn.addEventListener('click', () => {
    if (!activeCharacterId) return;
    const char = characters.find(c => c.id === activeCharacterId);
    if (!char) return;
    // Reset modal state
    avatarStyleSelect.value = 'sfw_default';
    avatarCustomPrompt.style.display = 'none';
    avatarCustomPrompt.value = _avatarBestGuessPrompt(char);
    // Show the NSFW optgroup only on patched NSFW builds. The server
    // injects a body class via /api/config when NSFW_MODE is on.
    if (avatarNsfwGroup) {
        avatarNsfwGroup.style.display =
            document.body.classList.contains('nsfw-build') ? '' : 'none';
    }
    avatarModal.classList.remove('hidden');
});

avatarStyleSelect.addEventListener('change', () => {
    avatarCustomPrompt.style.display =
        avatarStyleSelect.value === 'custom' ? 'block' : 'none';
});

document.getElementById('avatar-cancel').addEventListener('click', () => {
    avatarModal.classList.add('hidden');
});

document.getElementById('avatar-generate-now').addEventListener('click', async () => {
    if (!activeCharacterId) return;
    avatarModal.classList.add('hidden');
    overlay.classList.remove('hidden');
    document.querySelector('#loading-overlay p').textContent = "Synthesizing Avatar...";
    _showGenerationCircle('Conjuring avatar...');
    const styleKey = avatarStyleSelect.value;
    const customPrompt = (styleKey === 'custom')
        ? avatarCustomPrompt.value.trim()
        : (_AVATAR_STYLE_PROMPTS[styleKey] || "");
    try {
        const response = await fetch('/api/avatar_generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: activeCharacterId,
                comfy_url: comfyUrl,
                style_prompt: customPrompt,   // server appends to base prompt
                style_key: styleKey,
            })
        });
        const data = await response.json();
        if (data.avatar_url) {
            const char = characters.find(c => c.id === activeCharacterId);
            char.avatar_url = data.avatar_url;
            saveIdentity(char);
            const sep = data.avatar_url.includes('?') ? '&' : '?';
            activeAvatar.style.backgroundImage = `url('${data.avatar_url}${sep}t=${Date.now()}')`;
            renderSidebar(searchInput.value);
            addSystemMessage(`<strong>Avatar Updated!</strong><br>Generated new ${styleKey.replace('_', ' ')} avatar for ${char.name}.`);
        } else if (data.error) {
            addSystemMessage(`<strong>Avatar Failed!</strong><br>${data.error}`);
        }
    } catch (e) {
        addSystemMessage(`<strong>Avatar Failed!</strong><br>${e.message}`);
        console.error(e);
    }
    document.querySelector('#loading-overlay p').textContent = "The Guild is thinking...";
    overlay.classList.add('hidden');
    _hideGenerationCircle();
});

// Background generation modal
const bgModal = document.getElementById('bg-modal');
const bgStyleSelect = document.getElementById('bg-style-select');
const bgCustomPrompt = document.getElementById('bg-custom-prompt');
const bgModelSelect = document.getElementById('bg-model-select');

bgStyleSelect.addEventListener('change', () => {
    bgCustomPrompt.style.display = bgStyleSelect.value === 'custom' ? 'block' : 'none';
});

// Populate model dropdown when modal opens
async function loadAvailableModels() {
    try {
        const res = await fetch('/api/available_models');
        const models = await res.json();
        bgModelSelect.innerHTML = '<option value="auto">Auto-detect best model</option>';
        models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.name;
            opt.textContent = `${m.name} (${m.arch})`;
            bgModelSelect.appendChild(opt);
        });
    } catch(e) { console.error('Failed to load models:', e); }
}

generateBgBtn.addEventListener('click', () => {
    if(!activeCharacterId) return;
    loadAvailableModels();
    bgModal.classList.remove('hidden');
});

document.getElementById('bg-cancel').addEventListener('click', () => {
    bgModal.classList.add('hidden');
});

document.getElementById('bg-generate').addEventListener('click', async () => {
    bgModal.classList.add('hidden');
    overlay.classList.remove('hidden');
    const styleName = bgStyleSelect.options[bgStyleSelect.selectedIndex].text.split(' (')[0];
    document.querySelector('#loading-overlay p').textContent = `Conjuring ${styleName} background...`;
    try {
        const bgRes = getOptimalBgResolution();
        const response = await fetch('/api/background_generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                comfy_url: comfyUrl,
                style: bgStyleSelect.value,
                custom_prompt: bgCustomPrompt.value,
                model: bgModelSelect.value,
                width: bgRes.width,
                height: bgRes.height,
            })
        });
        const data = await response.json();
        if(data.bg_url) {
            localStorage.setItem('guild_global_bg', data.bg_url);
            applyGlobalBackground();
            addSystemMessage(`<strong>Tavern Remodeled!</strong><br>Generated new ${styleName} background.`);
        } else if(data.error) {
            addSystemMessage(`<strong>Background Failed!</strong><br>${data.error}`);
        }
    } catch(e) {
        addSystemMessage(`<strong>Background Failed!</strong><br>${e.message}`);
        console.error(e);
    }
    document.querySelector('#loading-overlay p').textContent = "The Guild is thinking...";
    overlay.classList.add('hidden');
});

// Batch Generate All
batchGenerateBtn.addEventListener('click', async () => {
    if(batchGenerateBtn.classList.contains('running')) return;
    batchGenerateBtn.classList.add('running');
    batchGenerateBtn.textContent = '⚡ Generating...';
    _showGenerationCircle('Batch spell in progress...');
    addSystemMessage('<strong>Batch Generation Started!</strong><br>Queuing avatars for all guild members + tavern background via ComfyUI. This runs in the background — you can keep chatting.');

    try {
        const batchBgRes = getOptimalBgResolution();
        const response = await fetch('/api/batch_generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comfy_url: comfyUrl, bg_width: batchBgRes.width, bg_height: batchBgRes.height })
        });
        const data = await response.json();
        if(data.status === 'started') {
            const pollInterval = setInterval(async () => {
                try {
                    const statusRes = await fetch('/api/batch_status');
                    const status = await statusRes.json();

                    for(const result of status.results) {
                        if(result.status === 'ok' && result.avatar_url) {
                            const char = characters.find(c => c.id === result.id);
                            if(char && !char._batch_applied) {
                                char.avatar_url = result.avatar_url;
                                char._batch_applied = true;
                                saveIdentity(char);
                                if(char.id === activeCharacterId) {
                                    const sep = result.avatar_url.includes('?') ? '&' : '?';
                                    activeAvatar.style.backgroundImage = `url('${result.avatar_url}${sep}t=${Date.now()}')`;
                                }
                                renderSidebar(searchInput.value);
                            }
                        }
                        if(result.status === 'ok' && result.bg_url) {
                            localStorage.setItem('guild_global_bg', result.bg_url);
                            applyGlobalBackground();
                        }
                    }

                    batchGenerateBtn.textContent = `⚡ ${status.completed}/${status.total}`;

                    if(!status.running) {
                        clearInterval(pollInterval);
                        const ok = status.results.filter(r => r.status === 'ok').length;
                        const fail = status.results.filter(r => r.status === 'error').length;
                        batchGenerateBtn.classList.remove('running');
                        batchGenerateBtn.textContent = '⚡ Generate All';
                        characters.forEach(c => delete c._batch_applied);
                        _hideGenerationCircle();
                        addSystemMessage(`<strong>Batch Complete!</strong><br>${ok} succeeded, ${fail} failed.`);
                    }
                } catch(e) {
                    console.error('Batch poll error:', e);
                }
            }, 3000);
        }
    } catch(e) {
        console.error(e);
        batchGenerateBtn.classList.remove('running');
        batchGenerateBtn.textContent = '⚡ Generate All';
        addSystemMessage('<strong>Batch Failed</strong><br>Could not start batch generation. Check ComfyUI connection.');
    }
});

// Rename Modal
renameBtn.addEventListener('click', () => {
    if(!activeCharacterId) return;
    const char = characters.find(c => c.id === activeCharacterId);
    renameInput.value = char.name === "Unnamed Wizard" ? "" : char.name;
    renameModal.classList.remove('hidden');
    renameInput.focus();
});

renameCancel.addEventListener('click', () => {
    renameModal.classList.add('hidden');
});

renameSave.addEventListener('click', () => {
    if(!activeCharacterId) return;
    const char = characters.find(c => c.id === activeCharacterId);
    const newName = renameInput.value.trim() || "Unnamed Wizard";
    char.name = newName;
    char._user_renamed = true;
    saveIdentity(char);
    activeName.textContent = newName;
    renameModal.classList.add('hidden');
    renderSidebar(searchInput.value);
    addSystemMessage(`<strong>Name Synthesized!</strong><br>Wizard's identity has been successfully registered as ${newName}.`);
});

renameLlmBtn.addEventListener('click', async () => {
    if(!activeCharacterId) return;
    const char = characters.find(c => c.id === activeCharacterId);
    
    // Feedback placeholder
    renameInput.value = "Generating...";
    
    let context = `Context: We are naming magical avatars.\nCommand: Invent a single, very short, creative fantasy name (e.g. Zephyr) for a wizard specializing in: ${char.subtext}. Do NOT use titles like 'Master of'.\nName:`;
    try {
        const data = await llmGenerate({ prompt: context, max_length: 15, temperature: 0.8, stop_sequence: ["\n", "."] });
        let llmName = data.results[0].text.trim().replace(/["']/g, '');
        renameInput.value = llmName;
    } catch(e) {
        console.error(e);
        renameInput.value = "Connection Error";
    }
});

// ═══════════════════════════════════════════════════════════════════════
//  Wizard Management (Banish / Unbanish) inside Settings
// ═══════════════════════════════════════════════════════════════════════

const wizardMgmtList = document.getElementById('wizard-mgmt-list');
const wizardMgmtSearch = document.getElementById('wizard-mgmt-search');
const wizardMgmtFilter = document.getElementById('wizard-mgmt-filter');

async function loadWizardManagement() {
    wizardMgmtList.innerHTML = '<p style="color:#666;padding:12px;text-align:center;">Loading...</p>';
    try {
        const res = await fetch('/api/all_characters');
        const allChars = await res.json();
        renderWizardMgmt(allChars);
    } catch(e) {
        wizardMgmtList.innerHTML = `<p style="color:#ff4757;padding:12px;">${e.message}</p>`;
    }
}

function renderWizardMgmt(allChars) {
    const filter = wizardMgmtFilter.value;
    const search = wizardMgmtSearch.value.toLowerCase();

    let filtered = allChars;
    if (filter === 'active') filtered = allChars.filter(c => !c.banished);
    if (filter === 'banished') filtered = allChars.filter(c => c.banished);
    if (search) filtered = filtered.filter(c =>
        c.name.toLowerCase().includes(search) ||
        c.subtext.toLowerCase().includes(search) ||
        c.id.toLowerCase().includes(search)
    );

    if (!filtered.length) {
        wizardMgmtList.innerHTML = '<p style="color:#666;padding:12px;text-align:center;">No wizards match.</p>';
        return;
    }

    wizardMgmtList.innerHTML = '';
    filtered.forEach(c => {
        const row = document.createElement('div');
        row.className = 'wizard-mgmt-row';
        row.innerHTML = `
            <div style="flex:1;min-width:0;">
                <div style="font-size:13px;color:${c.banished ? '#666' : '#eee'};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${c.id}">
                    ${c.name}${c.banished ? ' <span style="color:#ff4757;font-size:11px;">(banished)</span>' : ''}
                </div>
                <div style="font-size:11px;color:#666;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${c.subtext}</div>
            </div>
            <button class="wizard-mgmt-btn ${c.banished ? 'restore' : 'banish'}" data-id="${c.id}" data-banished="${c.banished}">
                ${c.banished ? 'Restore' : 'Banish'}
            </button>
        `;
        const btn = row.querySelector('.wizard-mgmt-btn');
        btn.addEventListener('click', async () => {
            const isBanished = btn.dataset.banished === 'true';
            const endpoint = isBanished ? '/api/unbanish_wizard' : '/api/banish_wizard';
            try {
                await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: btn.dataset.id })
                });
                // Toggle state in the local allChars array
                c.banished = !isBanished;
                renderWizardMgmt(allChars);

                // Refresh the main character list
                const charRes = await fetch('/api/characters');
                characters = await charRes.json();
                // Re-apply saved identities
                let savedIdentities = JSON.parse(localStorage.getItem('guild_identities') || '{}');
                characters.forEach(char => {
                    if(savedIdentities[char.id]) {
                        char.name = savedIdentities[char.id].name || char.name;
                        char.personality = savedIdentities[char.id].personality || char.personality;
                        char.avatar_url = savedIdentities[char.id].avatar_url || char.avatar_url;
                    }
                });
                renderSidebar(searchInput.value);

                // If the active character was banished, switch to first available
                if (!isBanished && activeCharacterId === btn.dataset.id && characters.length > 0) {
                    selectCharacter(characters[0].id);
                }
            } catch(e) {
                console.error('Banish/unbanish failed:', e);
            }
        });
        wizardMgmtList.appendChild(row);
    });
}

// Shared allChars cache for re-filtering without refetching
let _allCharsCache = [];
async function loadAndCacheWizards() {
    try {
        const res = await fetch('/api/all_characters');
        _allCharsCache = await res.json();
        renderWizardMgmt(_allCharsCache);
    } catch(e) {
        wizardMgmtList.innerHTML = `<p style="color:#ff4757;padding:12px;">${e.message}</p>`;
    }
}

wizardMgmtSearch.addEventListener('input', () => renderWizardMgmt(_allCharsCache));
wizardMgmtFilter.addEventListener('change', () => renderWizardMgmt(_allCharsCache));

// Settings Modal
settingsBtn.addEventListener('click', () => {
    settingsModal.classList.remove('hidden');
    // Sync LLM mode toggle to current state
    setLlmMode(llmMode);
    const hordeKeyInput = document.getElementById('horde-api-key-input');
    const hordeModelInput = document.getElementById('horde-model-input');
    if (hordeKeyInput) hordeKeyInput.value = localStorage.getItem('horde_api_key') || '';
    if (hordeModelInput) hordeModelInput.value = localStorage.getItem('horde_model') || '';
    loadAndCacheWizards();
});
settingsCancel.addEventListener('click', () => settingsModal.classList.add('hidden'));
settingsSave.addEventListener('click', async () => {
    // LLM mode
    const pendingMode = document.getElementById('llm-mode-local').dataset.pendingMode || 'local';
    llmMode = pendingMode;
    localStorage.setItem('llm_mode', llmMode);

    koboldUrl = koboldUrlInput.value.trim();
    localStorage.setItem('kobold_url', koboldUrl);

    // Horde settings
    const hordeKey = (document.getElementById('horde-api-key-input') || {}).value || '';
    const hordeModel = (document.getElementById('horde-model-input') || {}).value || '';
    localStorage.setItem('horde_api_key', hordeKey.trim());
    localStorage.setItem('horde_model', hordeModel.trim());

    comfyUrl = comfyUrlInput.value.trim();
    localStorage.setItem('comfy_url', comfyUrl);

    stUrl = stUrlInput.value.trim();
    localStorage.setItem('sillytavern_url', stUrl);

    bridgeUrl = bridgeUrlInput.value.trim();
    localStorage.setItem('signal_bridge_url', bridgeUrl);

    // Push config to server (persists to guild_config.json)
    try {
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                llm_mode: llmMode,
                kobold_url: koboldUrl,
                comfyui_url: comfyUrl,
                sillytavern_url: stUrl,
                signal_bridge_url: bridgeUrl,
                horde_api_key: hordeKey.trim(),
                horde_model: hordeModel.trim()
            })
        });
    } catch(e) { console.warn('Failed to push config to server:', e); }

    settingsModal.classList.add('hidden');

    // Refresh privacy banner based on new mode
    _updatePrivacyBanner();

    // Re-check connections with new URLs
    await checkLlmAndGenerateNames();
    await checkComfyConnection();
    await checkSillyTavernConnection();
    await checkSignalBridgeConnection();
});

// ═══════════════════════════════════════════════════════════════════════
//  Re-initialize / Nuke — wipe non-core wizards and re-detect
// ═══════════════════════════════════════════════════════════════════════

// Wipe-everything button — calls /api/setup/wipe to delete every
// generated avatar and background, clear the persistent setup marker,
// and reset _SETUP_STATE so the Archivist re-fires on next reload.
const wipeAssetsBtn = document.getElementById('wipe-assets-btn');
const wipeStatus = document.getElementById('wipe-status');
if (wipeAssetsBtn) {
    wipeAssetsBtn.addEventListener('click', async () => {
        if (!confirm(
            'This will DELETE every avatar, every background, and every '
            + 'cached generation file from your Wizard Guild folder.\n\n'
            + 'On next page reload the Archivist will re-fire setup mode '
            + 'and you can pick fresh avatar styles for each wizard.\n\n'
            + 'Wizard names, personalities, custom presets, and LoRA toggles '
            + 'are NOT touched — only generated images.\n\n'
            + 'Continue?'
        )) return;

        wipeAssetsBtn.disabled = true;
        wipeAssetsBtn.textContent = 'Wiping...';
        wipeStatus.style.display = 'block';
        wipeStatus.textContent = 'Deleting generated assets...';

        try {
            const res = await fetch('/api/setup/wipe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });
            const data = await res.json();
            if (res.ok && data.ok) {
                // Clear localStorage too so a fresh load isn't tricked
                // by a stale cached avatar URL.
                try {
                    const ids = JSON.parse(localStorage.getItem('guild_identities') || '{}');
                    for (const k of Object.keys(ids)) {
                        if (ids[k]) {
                            delete ids[k].avatar_url;
                            delete ids[k].animated_url;
                        }
                    }
                    localStorage.setItem('guild_identities', JSON.stringify(ids));
                    localStorage.removeItem('guild_global_bg');
                    localStorage.removeItem('guild_setup_complete');
                } catch (e) {}
                wipeStatus.textContent = `Wiped ${data.wiped_assets} entries + ${data.wiped_files} files. Reloading...`;
                setTimeout(() => location.reload(), 800);
            } else {
                wipeStatus.textContent = `Failed: ${(data.errors || []).join(', ') || 'unknown'}`;
                wipeAssetsBtn.disabled = false;
                wipeAssetsBtn.textContent = '⚠ Wipe Every Avatar & Background';
            }
        } catch (e) {
            wipeStatus.textContent = `Error: ${e.message}`;
            wipeAssetsBtn.disabled = false;
            wipeAssetsBtn.textContent = '⚠ Wipe Every Avatar & Background';
        }
    });
}

const restartBtn = document.getElementById('restart-server-btn');
const restartStatus = document.getElementById('restart-status');
if (restartBtn) {
    restartBtn.addEventListener('click', async () => {
        if (!confirm('Restart the Wizard Guild process? Browser will reconnect in ~3s.')) return;
        restartBtn.disabled = true;
        restartBtn.textContent = '⟳ Restarting…';
        restartStatus.style.display = 'block';
        restartStatus.textContent = 'Asking the server to restart…';
        try {
            await fetch('/api/guild/restart', { method: 'POST' });
        } catch (e) { /* expected: socket dies mid-response */ }
        restartStatus.textContent = 'Server down — waiting for it to come back up…';
        // Poll /api/comfy_status (cheap, existing) until it responds,
        // then reload the tab so every bit of state is fresh.
        const started = Date.now();
        const timer = setInterval(async () => {
            try {
                const r = await fetch('/api/comfy_status',
                                       { cache: 'no-store' });
                if (r.ok) { clearInterval(timer); window.location.reload(); }
            } catch (e) { /* server still coming up */ }
            if (Date.now() - started > 45000) {
                clearInterval(timer);
                restartStatus.textContent =
                    'Server did not come back within 45s. Reload manually.';
                restartBtn.disabled = false;
                restartBtn.textContent = '⟳ Restart Wizard Guild';
            }
        }, 1000);
    });
}

const reinitBtn = document.getElementById('reinit-btn');
const reinitKeepAssets = document.getElementById('reinit-keep-assets');
const reinitStatus = document.getElementById('reinit-status');

reinitBtn.addEventListener('click', async () => {
    if (!confirm(
        'This will remove ALL auto-detected and custom wizards, '
        + 'clear banished lists, reset the LoRA registry, '
        + 'and re-scan ComfyUI for models.\n\n'
        + 'Core wizards (Imaginus, Transmutex, Masquerade, etc.) are preserved.\n\n'
        + 'Continue?'
    )) return;

    reinitBtn.disabled = true;
    reinitBtn.textContent = 'Re-initializing...';
    reinitStatus.style.display = 'block';
    reinitStatus.textContent = 'Clearing non-core wizards and re-detecting from ComfyUI...';

    try {
        const res = await fetch('/api/reinitialize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                keep_core_assets: reinitKeepAssets.checked,
            })
        });
        const data = await res.json();

        if (res.ok) {
            // Clear frontend state for non-core wizards
            let savedIdentities = JSON.parse(localStorage.getItem('guild_identities') || '{}');

            if (!reinitKeepAssets.checked) {
                // Nuke all identities
                savedIdentities = {};
                localStorage.removeItem('guild_global_bg');
            } else {
                // Keep only core wizard identities (studio_*, model_*)
                const coreTypes = new Set(['studio', 'model_wizard']);
                const newIdentities = {};
                for (const [charId, identity] of Object.entries(savedIdentities)) {
                    // Core wizard IDs start with 'studio_' or 'model_'
                    if (charId.startsWith('studio_') || charId.startsWith('model_')) {
                        newIdentities[charId] = identity;
                    }
                }
                savedIdentities = newIdentities;
            }
            localStorage.setItem('guild_identities', JSON.stringify(savedIdentities));

            // Clear LoRA frontend state
            localStorage.removeItem('lora_enabled');
            localStorage.removeItem('lora_notified');
            loraEnabledState = {};
            _loraNotifiedWizards = new Set();

            // Clear setup flag so first-time setup can run for new wizards
            localStorage.removeItem('guild_setup_complete');

            reinitStatus.style.color = '#2ed573';
            reinitStatus.textContent =
                `Done! Removed ${data.removed} wizard(s), re-detected ${data.new_detected} from ComfyUI. ` +
                `Total: ${data.total} wizards. Reloading...`;

            // Reload the page to pick up the new character list
            setTimeout(() => window.location.reload(), 1500);
        } else {
            reinitStatus.style.color = '#ff4757';
            reinitStatus.textContent = `Error: ${data.error || 'Unknown error'}`;
        }
    } catch(e) {
        reinitStatus.style.color = '#ff4757';
        reinitStatus.textContent = `Failed: ${e.message}`;
    }

    reinitBtn.disabled = false;
    reinitBtn.textContent = 'Re-initialize & Re-detect All Models';
});

// ═══════════════════════════════════════════════════════════════════════
//  Summon Wizard — create new wizards from ComfyUI models
// ═══════════════════════════════════════════════════════════════════════

const summonBtn = document.getElementById('summon-wizard-btn');
const summonModal = document.getElementById('summon-modal');
const summonModelList = document.getElementById('summon-model-list');
const summonScaffoldSelect = document.getElementById('summon-scaffold-select');
const summonNext = document.getElementById('summon-next');
const summonCancel = document.getElementById('summon-cancel');
const summonStep1 = document.getElementById('summon-step-1');
const summonStep2 = document.getElementById('summon-step-2');
const summonBack = document.getElementById('summon-back');
const summonRegenerate = document.getElementById('summon-regenerate');
const summonCreate = document.getElementById('summon-create');

let selectedSummonModel = null;
let summonFlow = {
    archetype: 'per_model',       // 'per_model' | 'forensic' | 'chimera' | 'oracle' | 'lore_keeper' | 'scalpel'
    chimeraPicks: [],              // [{name,arch,type,domain}, ...]
    oracleConfig: {llm_model: 'gemma3:4b'},
    scalpelBase: null,
};

// ── Archetype catalogue ────────────────────────────────────────────────
// Drives the archetype picker cards AND the per-archetype config step.
// Each entry has an id, display metadata, and the required-model flag
// (some archetypes don't tie to a model — Forensic / Lore-keeper).
const SUMMON_ARCHETYPES = [
    {
        id: 'per_model',
        icon: '✦',
        title: 'Per-model Wizard',
        pitch: 'Classic. Bind one ComfyUI model to one persona with a matching studio (txt2img / video / faceswap / etc).',
        badge: 'CLASSIC',
    },
    {
        id: 'forensic',
        icon: '🔎',
        title: 'Forensic',
        pitch: 'Paste any PNG — Forensic extracts the embedded workflow (prompt, model, seed, LoRAs) and lets you remix it.',
        badge: 'ARCHETYPE',
    },
    {
        id: 'chimera',
        icon: '🌀',
        title: 'Chimera',
        pitch: 'Multimodal router. Pick 2–5 models; Chimera dispatches each prompt to the best fit or parallel-renders + scorer-picks a winner.',
        badge: 'ARCHETYPE',
    },
    {
        id: 'oracle',
        icon: '👁',
        title: 'Oracle',
        pitch: 'Vision reader. Drop an image — Oracle describes, critiques, and suggests improvements via a local multimodal LLM.',
        badge: 'ARCHETYPE',
    },
    {
        id: 'lore_keeper',
        icon: '📜',
        title: 'Lore-keeper',
        pitch: 'Conversational LoRA knowledge base. "What\'s in this LoRA?" "What pairs well with Sinozick?" Uses Civitai + safetensors data.',
        badge: 'ARCHETYPE',
    },
    {
        id: 'scalpel',
        icon: '🗡',
        title: 'Scalpel',
        pitch: 'Natural-language semantic editing. "Erase the car." "Change her dress to red." Chains SAM3 + magic-eraser + Klein inpaint.',
        badge: 'ARCHETYPE',
    },
];

function renderArchetypeGrid() {
    const grid = document.getElementById('summon-archetype-grid');
    if (!grid) return;
    grid.innerHTML = '';
    SUMMON_ARCHETYPES.forEach(a => {
        const card = document.createElement('div');
        card.className = 'summon-archetype-card';
        card.dataset.arc = a.id;
        card.innerHTML = `
            <div class="arc-icon">${a.icon}</div>
            <div class="arc-title">${a.title}</div>
            <div class="arc-pitch">${a.pitch}</div>
            <span class="arc-badge">${a.badge}</span>
        `;
        card.addEventListener('click', () => selectArchetype(a.id));
        grid.appendChild(card);
    });
}

function showStep(which) {
    const ids = ['summon-step-0', 'summon-step-1', 'summon-step-arc', 'summon-step-2'];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = (id === which ? '' : 'none');
    });
}

function selectArchetype(archId) {
    summonFlow.archetype = archId;
    if (archId === 'per_model') {
        selectedSummonModel = null;
        summonNext.disabled = true;
        showStep('summon-step-1');
        summonScaffoldSelect.value = 'auto';
        loadSummonModels();
        return;
    }
    // Archetype branch — go to the per-archetype config screen
    const meta = SUMMON_ARCHETYPES.find(a => a.id === archId);
    document.getElementById('summon-arc-title').textContent = `${meta.icon} ${meta.title}`;
    document.getElementById('summon-arc-desc').textContent = meta.pitch;
    // Hide all panels; show the right one
    ['summon-arc-chimera', 'summon-arc-oracle', 'summon-arc-scalpel', 'summon-arc-none']
        .forEach(id => { const el = document.getElementById(id); if (el) el.style.display = 'none'; });
    const nextBtn = document.getElementById('summon-arc-next');
    nextBtn.disabled = true;

    if (archId === 'chimera') {
        document.getElementById('summon-arc-chimera').style.display = '';
        loadChimeraModels();
    } else if (archId === 'oracle') {
        document.getElementById('summon-arc-oracle').style.display = '';
        loadOracleOptions();
        nextBtn.disabled = false;     // default gemma3:4b is always selectable
    } else if (archId === 'scalpel') {
        document.getElementById('summon-arc-scalpel').style.display = '';
        loadScalpelModels();
    } else {
        // forensic | lore_keeper — nothing to configure
        document.getElementById('summon-arc-none').style.display = '';
        nextBtn.disabled = false;
    }
    showStep('summon-step-arc');
}

async function loadChimeraModels() {
    const host = document.getElementById('summon-chimera-models');
    host.innerHTML = '<p style="color:#666;padding:12px;text-align:center;">Loading…</p>';
    summonFlow.chimeraPicks = [];
    try {
        const res = await fetch('/api/available_models');
        const models = await res.json();
        if (!models.length) {
            host.innerHTML = '<p style="color:#ff4757;padding:12px;text-align:center;">No models found.</p>';
            return;
        }
        host.innerHTML = '';
        // Filter out video archs — chimera routes text→image; video is its
        // own domain handled by Videomancer.
        const imageModels = models.filter(m => !/wan|ltx|svd/i.test(m.arch || m.name || ''));
        imageModels.forEach(m => {
            const row = document.createElement('div');
            row.className = 'summon-chimera-row';
            row.innerHTML = `
                <input type="checkbox" data-name="${m.name}" />
                <div style="flex:1;min-width:0">
                    <div style="font-size:13px;color:#eee;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${m.name}">${m.name}</div>
                    <div style="font-size:11px;color:#888;margin-top:2px">${archBadge(m.arch)}</div>
                </div>
                <select class="domain-select">
                    <option value="auto">auto</option>
                    <option value="portraits">portraits</option>
                    <option value="landscapes">landscapes</option>
                    <option value="anime">anime</option>
                    <option value="photoreal">photoreal</option>
                    <option value="painted">painted</option>
                    <option value="nsfw">nsfw</option>
                </select>
            `;
            const cb = row.querySelector('input[type=checkbox]');
            const sel = row.querySelector('.domain-select');
            const updatePicks = () => {
                summonFlow.chimeraPicks = [];
                host.querySelectorAll('.summon-chimera-row').forEach(r => {
                    const chk = r.querySelector('input[type=checkbox]');
                    if (!chk.checked) return;
                    const modelName = chk.dataset.name;
                    const mm = imageModels.find(x => x.name === modelName);
                    summonFlow.chimeraPicks.push({
                        name: mm.name, arch: mm.arch, type: mm.type,
                        domain: r.querySelector('.domain-select').value,
                    });
                });
                const n = summonFlow.chimeraPicks.length;
                document.getElementById('summon-arc-next').disabled = (n < 2 || n > 5);
            };
            cb.addEventListener('change', updatePicks);
            sel.addEventListener('change', updatePicks);
            host.appendChild(row);
        });
    } catch (e) {
        host.innerHTML = `<p style="color:#ff4757;padding:12px;text-align:center">Failed: ${e.message}</p>`;
    }
}

async function loadOracleOptions() {
    const statusEl = document.getElementById('summon-oracle-status');
    const sel = document.getElementById('summon-oracle-llm');
    statusEl.textContent = 'Probing local Ollama for vision models…';
    try {
        const r = await fetch('/api/spellcaster/lora/scorer/probe');
        const data = await r.json();
        if (data.ok) {
            statusEl.innerHTML = `<span style="color:#20c997">● online</span> — <code>${data.model}</code> installed.`;
            summonFlow.oracleConfig.llm_model = data.model;
        } else {
            statusEl.innerHTML = `<span style="color:#e03131">● offline</span> — ${data.reason || 'scorer probe failed'}. Summon will still work; install gemma3:4b to activate vision.`;
        }
        // Populate selector with any models the probe surfaced
        if (data.installed && data.installed.length) {
            sel.innerHTML = '';
            data.installed.forEach(n => {
                const opt = document.createElement('option');
                opt.value = n; opt.textContent = n;
                if (n === data.model) opt.selected = true;
                sel.appendChild(opt);
            });
        }
        sel.addEventListener('change', () => {
            summonFlow.oracleConfig.llm_model = sel.value;
        });
    } catch (e) {
        statusEl.textContent = 'Probe failed: ' + e.message;
    }
}

async function loadScalpelModels() {
    const host = document.getElementById('summon-scalpel-models');
    host.innerHTML = '<p style="color:#666;padding:12px;text-align:center;">Loading…</p>';
    summonFlow.scalpelBase = null;
    try {
        const res = await fetch('/api/available_models');
        const models = await res.json();
        const inpaintable = models.filter(m =>
            !/wan|ltx|svd|upscale|esrgan|reactor|faceswap/i.test(m.arch + ' ' + m.name)
        );
        host.innerHTML = '';
        inpaintable.forEach(m => {
            const row = document.createElement('div');
            row.className = 'summon-scalpel-row';
            row.innerHTML = `
                <div style="flex:1;min-width:0">
                    <div style="font-size:13px;color:#eee;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${m.name}">${m.name}</div>
                    <div style="font-size:11px;color:#888;margin-top:2px">${archBadge(m.arch)}</div>
                </div>
            `;
            row.addEventListener('click', () => {
                host.querySelectorAll('.summon-scalpel-row.selected').forEach(r => r.classList.remove('selected'));
                row.classList.add('selected');
                summonFlow.scalpelBase = { name: m.name, arch: m.arch, type: m.type };
                document.getElementById('summon-arc-next').disabled = false;
            });
            host.appendChild(row);
        });
    } catch (e) {
        host.innerHTML = `<p style="color:#ff4757;padding:12px;text-align:center">Failed: ${e.message}</p>`;
    }
}

// Scaffold auto-detect mapping
function guessScaffold(modelName, arch) {
    const ml = modelName.toLowerCase();
    if (/wan|ltx|video|animate|svd|cog/.test(ml)) return 'video_gen';
    if (/seedvr|rife|rtx_upscale/.test(ml)) return 'video_upscale';
    if (/upscale|esrgan|ultrasharp|remacri|nmkd/.test(ml)) return 'studio_restorix';
    if (/inpaint/.test(ml)) return 'studio_erasure';
    if (/reactor|faceswap|pulid|faceid|insightface/.test(ml)) return 'studio_masquerade';
    if (/img2img|pix2pix|instruct/.test(ml)) return 'studio_transmutex';
    // Default: image creation for any generative checkpoint/unet
    return 'studio_imaginus';
}

function getScaffoldLabel(val) {
    const labels = {
        'auto': 'Auto-detect',
        'studio_imaginus': 'Image Creation (txt2img, ControlNet)',
        'studio_transmutex': 'Image Transformation (img2img, Style Transfer)',
        'studio_masquerade': 'Face & Identity (Face Swap, FaceID, PuLID)',
        'studio_restorix': 'Upscaling & Restoration',
        'studio_erasure': 'Inpainting, Removal & Edits',
        'video_gen': 'Video Generation',
        'video_upscale': 'Video Upscaling & Enhancement',
        'generic': 'Generic Workflow Browser',
    };
    return labels[val] || val;
}

// Arch badge colors
function archBadge(arch) {
    const colors = {
        'flux2klein': '#B246F2',
        'flux1dev': '#6C63FF',
        'sdxl': '#2ed573',
        'illustrious': '#ffa502',
        'sd15': '#57606f',
        'unknown': '#444',
    };
    return `<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;background:${colors[arch]||'#444'};color:#fff;">${arch}</span>`;
}

async function loadSummonModels() {
    summonModelList.innerHTML = '<p style="color:#666;padding:12px;text-align:center;">Loading models from ComfyUI...</p>';
    try {
        const res = await fetch('/api/available_models');
        const models = await res.json();
        if (!models.length) {
            summonModelList.innerHTML = '<p style="color:#ff4757;padding:12px;text-align:center;">No models found. Is ComfyUI running?</p>';
            return;
        }

        // Check which models already have wizards
        const existingModels = new Set(characters.filter(c => c.model_name).map(c => c.model_name));

        summonModelList.innerHTML = '';
        models.forEach(m => {
            const exists = existingModels.has(m.name);
            const guessed = guessScaffold(m.name, m.arch);
            const row = document.createElement('div');
            row.className = 'summon-model-row' + (exists ? ' exists' : '');
            row.dataset.modelName = m.name;
            row.dataset.modelArch = m.arch;
            row.dataset.modelType = m.type;
            row.dataset.guessedScaffold = guessed;
            row.innerHTML = `
                <div style="flex:1;min-width:0;">
                    <div style="font-size:14px;color:${exists ? '#666' : '#eee'};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${m.name}">${m.name}</div>
                    <div style="font-size:11px;color:#888;margin-top:2px;">${m.type} ${archBadge(m.arch)} ${exists ? '<span style="color:#ffa502;margin-left:6px;">already summoned</span>' : ''}</div>
                </div>
                <div style="font-size:11px;color:#666;white-space:nowrap;">${getScaffoldLabel(guessed)}</div>
            `;
            if (!exists) {
                row.addEventListener('click', () => {
                    document.querySelectorAll('.summon-model-row.selected').forEach(r => r.classList.remove('selected'));
                    row.classList.add('selected');
                    selectedSummonModel = m;
                    summonScaffoldSelect.value = guessed;
                    summonNext.disabled = false;
                });
            }
            summonModelList.appendChild(row);
        });
    } catch(e) {
        summonModelList.innerHTML = `<p style="color:#ff4757;padding:12px;text-align:center;">Failed to load: ${e.message}</p>`;
    }
}

async function generateWizardIdentity() {
    if (!selectedSummonModel) return;
    const m = selectedSummonModel;
    const scaffold = summonScaffoldSelect.value === 'auto' ? guessScaffold(m.name, m.arch) : summonScaffoldSelect.value;

    // Show step 2
    summonStep1.style.display = 'none';
    summonStep2.style.display = 'block';
    document.getElementById('summon-preview-model').textContent = `${m.name} (${m.arch} / ${m.type})`;
    document.getElementById('summon-scaffold-label').textContent = getScaffoldLabel(scaffold);
    document.getElementById('summon-name-input').value = 'Generating...';
    document.getElementById('summon-personality-input').value = 'Generating...';
    document.getElementById('summon-subtext-input').value = `${m.name} — ${getScaffoldLabel(scaffold)}`;

    // Set avatar gradient from model hash
    const hue = Math.abs(m.name.split('').reduce((a,c) => a + c.charCodeAt(0), 0)) % 360;
    document.getElementById('summon-preview-avatar').style.background = `linear-gradient(135deg, hsl(${hue},85%,42%), hsl(${(hue+55)%360},100%,58%))`;

    // Generate name via LLM
    try {
        const nameCtx = `Context: We are naming magical wizard avatars for a ComfyUI image generation interface.\nThe wizard specializes in: ${getScaffoldLabel(scaffold)}.\nTheir primary model/tool is called "${m.name}" (architecture: ${m.arch}).\nCommand: Invent a single, very short, creative fantasy name (1-2 words, e.g. Zephyr, Duskweave, Pyralis) for this wizard. The name should hint at what the model does. Do NOT use titles like 'Master of'.\nName:`;
        const nameData = await llmGenerate({ prompt: nameCtx, max_length: 15, temperature: 0.85, stop_sequence: ["\n", "."] });
        const llmName = nameData.results[0].text.trim().replace(/["']/g, '');
        document.getElementById('summon-name-input').value = llmName || 'Unnamed Wizard';
    } catch(e) {
        document.getElementById('summon-name-input').value = 'Unnamed Wizard';
    }

    // Generate personality via LLM
    try {
        const persCtx = `Context: A magical wizard named "${document.getElementById('summon-name-input').value}" works in The Wizard Guild, a ComfyUI interface. They specialize in ${getScaffoldLabel(scaffold)} using the model "${m.name}".\nCommand: Write exactly one vivid, eccentric sentence describing their personality quirk and speaking style. Make them memorable — maybe dramatic, obsessive, sarcastic, poetic, or hilariously intense. Reference their specialty.\nPersonality:`;
        const persData = await llmGenerate({ prompt: persCtx, max_length: 80, temperature: 0.9, stop_sequence: ["\n"] });
        const llmPers = persData.results[0].text.trim();
        document.getElementById('summon-personality-input').value = llmPers || `A dedicated specialist in ${getScaffoldLabel(scaffold)}.`;
    } catch(e) {
        document.getElementById('summon-personality-input').value = `A dedicated specialist in ${getScaffoldLabel(scaffold)}.`;
    }
}

// Open modal — always lands on step 0 (archetype picker) first
summonBtn.addEventListener('click', () => {
    selectedSummonModel = null;
    summonFlow = {
        archetype: 'per_model',
        chimeraPicks: [],
        oracleConfig: {llm_model: 'gemma3:4b'},
        scalpelBase: null,
    };
    summonNext.disabled = true;
    renderArchetypeGrid();
    showStep('summon-step-0');
    summonScaffoldSelect.value = 'auto';
    summonModal.classList.remove('hidden');
});

document.getElementById('summon-step0-cancel').addEventListener('click', () => {
    summonModal.classList.add('hidden');
});

summonCancel.addEventListener('click', () => {
    summonModal.classList.add('hidden');
});

summonNext.addEventListener('click', () => {
    // Classic per-model flow: step 1 → step 2 identity gen
    generateWizardIdentity();
});

// Archetype config → identity step
document.getElementById('summon-arc-next').addEventListener('click', () => {
    generateArchetypeIdentity();
});
document.getElementById('summon-arc-back').addEventListener('click', () => {
    showStep('summon-step-0');
});

summonBack.addEventListener('click', () => {
    // From step 2 back to either step-1 (per_model) or step-arc (archetype)
    if (summonFlow.archetype === 'per_model') showStep('summon-step-1');
    else showStep('summon-step-arc');
});

// ── Archetype-aware identity generation ────────────────────────────────
async function generateArchetypeIdentity() {
    const archId = summonFlow.archetype;
    const meta = SUMMON_ARCHETYPES.find(a => a.id === archId);
    showStep('summon-step-2');
    document.getElementById('summon-preview-model').textContent = meta.title + ' archetype';
    document.getElementById('summon-scaffold-label').textContent = meta.pitch;
    document.getElementById('summon-name-input').value = 'Generating…';
    document.getElementById('summon-personality-input').value = 'Generating…';
    document.getElementById('summon-subtext-input').value = _archetypeDefaultSubtext(archId);
    const hue = (meta.title.charCodeAt(0) * 17 + meta.title.length * 53) % 360;
    document.getElementById('summon-preview-avatar').style.background =
        `linear-gradient(135deg, hsl(${hue},85%,42%), hsl(${(hue+55)%360},100%,58%))`;

    const prompts = _archetypeIdentityPrompts(archId, meta);
    try {
        const nameData = await llmGenerate({ prompt: prompts.namePrompt, max_length: 15, temperature: 0.9, stop_sequence: ["\n", "."] });
        const llmName = (nameData.results[0].text || '').trim().replace(/["']/g, '');
        document.getElementById('summon-name-input').value = llmName || meta.title;
    } catch { document.getElementById('summon-name-input').value = meta.title; }
    try {
        const name = document.getElementById('summon-name-input').value;
        const persData = await llmGenerate({ prompt: prompts.personalityPrompt(name), max_length: 90, temperature: 0.9, stop_sequence: ["\n"] });
        document.getElementById('summon-personality-input').value =
            (persData.results[0].text || '').trim() || prompts.personalityFallback;
    } catch { document.getElementById('summon-personality-input').value = _archetypeDefaultSubtext(archId); }
}

function _archetypeDefaultSubtext(archId) {
    const map = {
        forensic:    'Forensic — PNG workflow extraction + remix',
        chimera:     'Chimera — multi-model router',
        oracle:      'Oracle — vision reader + critique',
        lore_keeper: 'Lore-keeper — conversational LoRA knowledge base',
        scalpel:     'Scalpel — natural-language semantic editing',
    };
    return map[archId] || archId;
}

function _archetypeIdentityPrompts(archId, meta) {
    const flavour = {
        forensic:    'a detective who reverse-engineers AI image workflows from their metadata',
        chimera:     'a multi-headed router who picks the best image model per prompt',
        oracle:      'a vision-reading seer who describes and critiques generated images',
        lore_keeper: 'a scholar of every LoRA in the user\'s library who knows what each does and what pairs well',
        scalpel:     'a precision editor who erases, replaces, and reshapes parts of images via plain English',
    }[archId] || meta.pitch;
    return {
        namePrompt:
            `Context: Naming a magical wizard avatar in The Wizard Guild, a ComfyUI interface.\n` +
            `This wizard is "${meta.title}" — ${flavour}.\n` +
            `Command: Invent a single short creative fantasy name (1-2 words). Do NOT reuse the word "${meta.title}".\n` +
            `Name:`,
        personalityPrompt: (name) =>
            `Context: A wizard named "${name}" serves as The Wizard Guild's ${meta.title} — ${flavour}.\n` +
            `Command: Write exactly ONE vivid sentence describing their speaking style and personality quirk. Make them memorable.\n` +
            `Personality:`,
        personalityFallback:
            `A focused specialist in ${meta.title.toLowerCase()} work.`,
    };
}

summonRegenerate.addEventListener('click', () => {
    generateWizardIdentity();
});

summonCreate.addEventListener('click', async () => {
    const name = document.getElementById('summon-name-input').value.trim() || 'Unnamed Wizard';
    const personality = document.getElementById('summon-personality-input').value.trim();
    const subtext = document.getElementById('summon-subtext-input').value.trim();

    // Build the payload by archetype. per_model requires a selected
    // model; archetypes either use no model, one, or many depending on
    // their kind.
    let payload;
    if (summonFlow.archetype === 'per_model') {
        if (!selectedSummonModel) return;
        const m = selectedSummonModel;
        const scaffold = summonScaffoldSelect.value === 'auto'
            ? guessScaffold(m.name, m.arch) : summonScaffoldSelect.value;
        payload = {
            model_name: m.name, model_arch: m.arch, model_type: m.type,
            name, personality, subtext, scaffold,
        };
    } else {
        payload = {
            archetype_kind: summonFlow.archetype,
            name, personality, subtext,
        };
        if (summonFlow.archetype === 'chimera') {
            if (summonFlow.chimeraPicks.length < 2) return;
            payload.archetype_config = { models: summonFlow.chimeraPicks };
        } else if (summonFlow.archetype === 'oracle') {
            payload.archetype_config = { ...summonFlow.oracleConfig };
        } else if (summonFlow.archetype === 'scalpel') {
            if (!summonFlow.scalpelBase) return;
            payload.archetype_config = { base_model: summonFlow.scalpelBase };
        } else {
            payload.archetype_config = {};
        }
    }

    summonCreate.disabled = true;
    summonCreate.textContent = 'Summoning...';

    try {
        const res = await fetch('/api/summon_wizard', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (res.ok && data.character) {
            // Add to local characters list
            const newChar = data.character;
            newChar.personality = personality;
            characters.push(newChar);
            saveIdentity(newChar);
            renderSidebar(searchInput.value);
            selectCharacter(newChar.id);

            summonModal.classList.add('hidden');
            const blurb = summonFlow.archetype === 'per_model'
                ? `${name} has joined the Guild, wielding the power of <em>${selectedSummonModel.name}</em>.`
                : `${name} has joined the Guild as a <em>${SUMMON_ARCHETYPES.find(a => a.id === summonFlow.archetype).title}</em> archetype.`;
            addSystemMessage(`<strong>Wizard Summoned!</strong><br>${blurb}`);

            // Auto-generate avatar in background
            try {
                const avatarRes = await fetch('/api/avatar_generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: newChar.id, comfy_url: comfyUrl })
                });
                const aData = await avatarRes.json();
                if (aData.avatar_url) {
                    newChar.avatar_url = aData.avatar_url;
                    saveIdentity(newChar);
                    const sep = aData.avatar_url.includes('?') ? '&' : '?';
                    activeAvatar.style.backgroundImage = `url('${aData.avatar_url}${sep}t=${Date.now()}')`;
                    renderSidebar(searchInput.value);
                    addSystemMessage(`<strong>Avatar Conjured!</strong><br>${name}'s portrait has been rendered.`);
                }
            } catch(e) { console.error('Avatar gen failed:', e); }
        } else {
            addSystemMessage(`<strong>Summon Failed!</strong><br>${data.error || 'Unknown error'}`);
        }
    } catch(e) {
        addSystemMessage(`<strong>Summon Failed!</strong><br>${e.message}`);
    }

    summonCreate.disabled = false;
    summonCreate.textContent = 'Summon Wizard';
});

// ═══════════════════════════════════════════════════════════════════════
//  LoRA Enchantment System — discovery, management, per-wizard toggles
// ═══════════════════════════════════════════════════════════════════════

const loraBtn = document.getElementById('lora-btn');
const loraModal = document.getElementById('lora-modal');
const loraModalTitle = document.getElementById('lora-modal-title');
const loraModalSubtitle = document.getElementById('lora-modal-subtitle');
const loraList = document.getElementById('lora-list');
const loraCountLabel = document.getElementById('lora-count-label');
const loraCloseBtn = document.getElementById('lora-close');
const loraRefreshBtn = document.getElementById('lora-refresh-btn');
const loraInterrogation = document.getElementById('lora-interrogation');
const loraInterrogationList = document.getElementById('lora-interrogation-list');
const loraInterrogationSkip = document.getElementById('lora-interrogation-skip');
const loraInterrogationSave = document.getElementById('lora-interrogation-save');

// Per-wizard LoRA enabled state: { char_id: { lora_name: true/false } }
let loraEnabledState = JSON.parse(localStorage.getItem('lora_enabled') || '{}');

function saveLoraState() {
    localStorage.setItem('lora_enabled', JSON.stringify(loraEnabledState));
    // Persist to server (fire-and-forget)
    fetch('/api/lora_toggles', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({toggles: loraEnabledState}),
    }).catch(() => {});
}

function getEnabledLoras(charId) {
    const state = loraEnabledState[charId] || {};
    return Object.keys(state).filter(k => state[k]);
}

// Open LoRA modal for the active wizard
loraBtn.addEventListener('click', async () => {
    if (!activeCharacterId) return;
    const char = characters.find(c => c.id === activeCharacterId);
    if (!char) return;

    loraModalTitle.textContent = `Enchantments — ${char.name || char.id}`;
    loraModalSubtitle.textContent = `Compatible LoRA enhancements for ${char.subtext || 'this wizard'}`;
    loraList.innerHTML = '<p style="color:#666;padding:12px;text-align:center;">Loading enchantments...</p>';
    loraInterrogation.style.display = 'none';
    loraModal.classList.remove('hidden');

    try {
        const res = await fetch(`/api/lora_registry/${activeCharacterId}`);
        const data = await res.json();
        renderLoraList(data.loras, activeCharacterId);

        // Show interrogation if there are unknown LoRAs and this wizard hasn't been interrogated
        if (data.unknown_count > 0 && !data.interrogated) {
            renderLoraInterrogation(data.loras.filter(l => !l.purpose && !l.user_desc), activeCharacterId);
        }

        loraCountLabel.textContent = `${data.loras.length} compatible / ${data.total_registry} total`;
    } catch(e) {
        loraList.innerHTML = `<p style="color:#ff4757;padding:12px;">${e.message}</p>`;
    }
});

loraCloseBtn.addEventListener('click', () => loraModal.classList.add('hidden'));

loraRefreshBtn.addEventListener('click', async () => {
    loraRefreshBtn.textContent = 'Refreshing...';
    loraRefreshBtn.disabled = true;
    try {
        await fetch('/api/lora_refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comfy_url: comfyUrl })
        });
        // Wait a moment for the background thread to populate
        await new Promise(r => setTimeout(r, 2000));
        // Re-open to show updated results
        loraBtn.click();
    } catch(e) {
        console.error('LoRA refresh failed:', e);
    }
    loraRefreshBtn.textContent = 'Refresh from ComfyUI';
    loraRefreshBtn.disabled = false;
});

function renderLoraList(loras, charId) {
    if (!loras.length) {
        loraList.innerHTML = '<p style="color:#888;padding:16px;text-align:center;">No compatible LoRAs found for this wizard\'s architecture.</p>';
        return;
    }

    if (!loraEnabledState[charId]) loraEnabledState[charId] = {};
    const state = loraEnabledState[charId];

    loraList.innerHTML = '';
    loras.forEach(lora => {
        const enabled = state[lora.name] || false;
        const purposeText = lora.purpose || lora.user_desc || 'unknown purpose';
        const sourceIcon = lora.source === 'civitai' ? '🌐' : lora.source === 'user' ? '✍️' : '❓';
        const civitLink = lora.civitai_url
            ? `<a href="${lora.civitai_url}" target="_blank" style="color:#B246F2;font-size:11px;text-decoration:none;margin-left:6px;">CivitAI ↗</a>`
            : '';

        // Trigger keyword badges + recommended strength chip — surface
        // anything the user (or CivitAI metadata) has captured about
        // how to invoke this LoRA.
        let triggerBadges = '';
        if (lora.trigger_words) {
            const words = String(lora.trigger_words).split(',').map(w => w.trim()).filter(Boolean);
            triggerBadges = words.map(w =>
                `<span style="display:inline-block;padding:1px 6px;margin:2px 3px 0 0;background:rgba(252,211,77,0.15);border:1px solid rgba(252,211,77,0.3);border-radius:4px;font-size:10px;color:#fde68a;font-family:monospace;">${w}</span>`
            ).join('');
        }
        const strengthChip = (lora.default_strength != null && lora.default_strength !== 0.7)
            ? `<span style="display:inline-block;padding:1px 6px;margin-left:4px;background:rgba(178,70,242,0.15);border:1px solid rgba(178,70,242,0.3);border-radius:4px;font-size:10px;color:#c4b5fd;">str ${lora.default_strength}</span>`
            : '';

        // Auto-blacklist surface: a LoRA that has racked up failures
        // against this wizard's checkpoint shows a red badge + Unblock
        // button. The checkbox is force-disabled so the user can't enable
        // a known-broken LoRA without clearing the failures first.
        const blockedBadge = lora.blocked
            ? `<span title="Auto-blocked after ${lora.failure_count} failed attempt(s) with this wizard's model" style="display:inline-block;padding:1px 6px;margin-left:4px;background:rgba(239,68,68,0.18);border:1px solid rgba(239,68,68,0.45);border-radius:4px;font-size:10px;color:#fca5a5;font-weight:600;">⚠ auto-blocked</span>`
            : '';
        const unblockBtn = lora.blocked
            ? `<button type="button" data-unblock="${lora.name}" style="margin-left:6px;padding:2px 8px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.4);border-radius:4px;color:#fca5a5;font-size:10px;cursor:pointer;">Unblock</button>`
            : '';

        const row = document.createElement('div');
        const blockedRowStyle = lora.blocked
            ? 'opacity:0.55;background:rgba(239,68,68,0.04);'
            : '';
        row.style.cssText = `display:flex;align-items:center;gap:10px;padding:10px 12px;border-bottom:1px solid #222;${blockedRowStyle}`;
        row.innerHTML = `
            <label style="display:flex;align-items:center;cursor:${lora.blocked ? 'not-allowed' : 'pointer'};flex-shrink:0;">
                <input type="checkbox" data-lora="${lora.name}" ${enabled && !lora.blocked ? 'checked' : ''} ${lora.blocked ? 'disabled' : ''}
                    style="width:18px;height:18px;accent-color:#B246F2;cursor:${lora.blocked ? 'not-allowed' : 'pointer'};">
            </label>
            <div style="flex:1;min-width:0;">
                <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                    <span style="font-weight:600;color:#eee;font-size:13px;">${lora.display_name}</span>
                    <span style="font-size:11px;color:#888;" title="${lora.source}">${sourceIcon}</span>
                    ${strengthChip}
                    ${blockedBadge}
                    ${unblockBtn}
                    ${civitLink}
                </div>
                <p style="color:#aaa;font-size:12px;margin-top:2px;">${purposeText}</p>
                ${triggerBadges ? `<div style="margin-top:3px;">${triggerBadges}</div>` : ''}
                ${lora.description ? `<p style="color:#666;font-size:11px;margin-top:2px;max-height:40px;overflow:hidden;">${lora.description.substring(0, 120)}</p>` : ''}
            </div>
        `;

        const checkbox = row.querySelector('input[type="checkbox"]');
        checkbox.addEventListener('change', () => {
            if (lora.blocked) { checkbox.checked = false; return; }
            state[lora.name] = checkbox.checked;
            saveLoraState();
        });

        const unblockEl = row.querySelector('button[data-unblock]');
        if (unblockEl) {
            unblockEl.addEventListener('click', async (ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                unblockEl.disabled = true;
                unblockEl.textContent = '...';
                try {
                    const char = characters.find(c => c.id === charId);
                    const r = await fetch('/api/lora_unblock', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            lora_name: lora.name,
                            model: (char && char.model_name) || '',
                        }),
                    });
                    if (r.ok) {
                        // Refresh the LoRA list so blocked state recomputes.
                        const refresh = await fetch(`/api/lora_registry/${charId}`);
                        if (refresh.ok) {
                            const fresh = await refresh.json();
                            renderLoraList(fresh.loras, charId);
                        }
                    } else {
                        unblockEl.disabled = false;
                        unblockEl.textContent = 'Unblock';
                    }
                } catch (e) {
                    unblockEl.disabled = false;
                    unblockEl.textContent = 'Unblock';
                }
            });
        }

        loraList.appendChild(row);
    });
}

function renderLoraInterrogation(unknownLoras, charId) {
    if (!unknownLoras.length) {
        loraInterrogation.style.display = 'none';
        return;
    }

    loraInterrogation.style.display = 'block';
    loraInterrogationList.innerHTML = '';

    // Helpful tips header so users know what they're doing
    const tips = document.createElement('div');
    tips.style.cssText = 'margin-bottom:12px;padding:10px 12px;background:rgba(252,211,77,0.06);border:1px solid rgba(252,211,77,0.2);border-radius:8px;color:#fde68a;font-size:12px;line-height:1.5;';
    tips.innerHTML = `
        <strong>Help me classify these LoRAs.</strong> For each one, tell me:
        <ul style="margin:6px 0 4px 18px;padding:0;">
            <li><strong>What it does</strong> (e.g. "hand refinement", "anime style", "detail enhance")</li>
            <li><strong>Trigger words</strong> if it has them — comma-separated keywords that activate the LoRA</li>
            <li><strong>Default strength</strong> — the recommended weight (0.0–2.0). Start with <code>0.7</code> and tune from there.</li>
        </ul>
        <span style="opacity:0.85;">Tip: don't stack more than 3 LoRAs in a single generation — they fight each other and quality drops.</span>
    `;
    loraInterrogationList.appendChild(tips);

    unknownLoras.forEach(lora => {
        const row = document.createElement('div');
        row.style.cssText = 'display:grid;grid-template-columns:160px 1fr 1fr 60px;gap:8px;margin-bottom:10px;align-items:center;';
        row.innerHTML = `
            <span style="font-weight:600;color:#ddd;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${lora.name}">${lora.display_name}</span>
            <input type="text" data-lora-name="${lora.name}" data-field="purpose"
                placeholder="What does it do? (e.g. hand fix, anime style)"
                style="padding:6px 10px;border-radius:6px;border:1px solid #444;background:#1a1a2e;color:#eee;font-size:12px;min-width:0;">
            <input type="text" data-lora-name="${lora.name}" data-field="trigger_words"
                placeholder="Trigger words (comma-separated, optional)"
                style="padding:6px 10px;border-radius:6px;border:1px solid #444;background:#1a1a2e;color:#eee;font-size:12px;min-width:0;">
            <input type="number" data-lora-name="${lora.name}" data-field="strength"
                placeholder="0.7" min="0" max="2" step="0.05" value="0.7"
                style="padding:6px 8px;border-radius:6px;border:1px solid #444;background:#1a1a2e;color:#eee;font-size:12px;text-align:center;">
        `;
        loraInterrogationList.appendChild(row);
    });
}

loraInterrogationSave.addEventListener('click', async () => {
    // Three columns of inputs per LoRA: purpose, trigger_words, strength.
    // Group by lora name and only send fields the user actually filled in.
    const inputs = loraInterrogationList.querySelectorAll('input[data-lora-name]');
    const descriptions = {};
    const trigger_words = {};
    const strengths = {};
    inputs.forEach(inp => {
        const name = inp.dataset.loraName;
        const field = inp.dataset.field;
        const val = inp.value.trim();
        if (!name || !val) return;
        if (field === 'purpose') descriptions[name] = val;
        else if (field === 'trigger_words') trigger_words[name] = val;
        else if (field === 'strength') {
            const num = parseFloat(val);
            if (!isNaN(num)) strengths[name] = num;
        }
    });

    if (Object.keys(descriptions).length === 0
        && Object.keys(trigger_words).length === 0
        && Object.keys(strengths).length === 0) {
        loraInterrogation.style.display = 'none';
        return;
    }

    try {
        await fetch('/api/lora_describe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                descriptions, trigger_words, strengths,
                char_id: activeCharacterId,
            }),
        });
        // Refresh the LoRA modal so the user sees their saved input
        loraBtn.click();
    } catch(e) {
        console.error('Failed to save LoRA descriptions:', e);
    }
});

loraInterrogationSkip.addEventListener('click', () => {
    loraInterrogation.style.display = 'none';
});

// ═══════════════════════════════════════════════════════════════════════
//  Splash Screen — wait for server, animate sigil, then reveal UI
// ═══════════════════════════════════════════════════════════════════════

async function _waitForServer(maxWait = 30000) {
    const start = Date.now();
    const bar = document.getElementById('splash-bar-fill');
    const status = document.getElementById('splash-status');
    let pct = 0;
    while (Date.now() - start < maxWait) {
        try {
            const r = await fetch('/api/config', { signal: AbortSignal.timeout(2000) });
            if (r.ok) {
                if (bar) bar.style.width = '100%';
                if (status) status.textContent = 'The Guild awaits...';
                return true;
            }
        } catch(e) { /* server not ready yet */ }
        pct = Math.min(85, pct + (85 - pct) * 0.15);
        if (bar) bar.style.width = pct + '%';
        await new Promise(r => setTimeout(r, 400));
    }
    return false;
}

function _animateSplashSigil() {
    if (typeof gsap === 'undefined' || document.hidden) return;
    const tl = gsap.timeline();
    // Outer ring draws in
    tl.to('#splash-ring-outer', { strokeDashoffset: 0, duration: 1.5, ease: 'power2.inOut' }, 0);
    // Inner ring draws in (staggered)
    tl.to('#splash-ring-inner', { strokeDashoffset: 0, duration: 1.2, ease: 'power2.inOut' }, 0.3);
    // Star fades in
    tl.to('#splash-star', { opacity: 0.7, duration: 0.8, ease: 'power1.in' }, 0.8);
    // Star slowly rotates
    tl.to('#splash-star', { rotation: 360, duration: 20, ease: 'none', repeat: -1, transformOrigin: '100px 100px' }, 0.8);
    // Eye opens
    tl.to('#splash-eye', { opacity: 0.9, duration: 0.5 }, 1.4);
    tl.to('#splash-pupil', { opacity: 1, duration: 0.3 }, 1.6);
    // Title and status
    tl.to('#splash-title', { opacity: 1, y: 0, duration: 0.8, ease: 'power3.out' }, 1.2);
    tl.to('#splash-status', { opacity: 1, duration: 0.6 }, 1.6);
    tl.to('#splash-bar-track', { opacity: 1, duration: 0.4 }, 1.8);
    // Floating motes
    for (let i = 0; i < 20; i++) {
        const mote = document.createElement('div');
        mote.className = 'splash-mote';
        document.getElementById('guild-splash').appendChild(mote);
        gsap.set(mote, {
            x: Math.random() * window.innerWidth,
            y: Math.random() * window.innerHeight,
            scale: Math.random() * 1.5 + 0.5,
            opacity: 0
        });
        gsap.to(mote, {
            y: '-=200', x: '+=' + (Math.random() * 100 - 50),
            opacity: Math.random() * 0.5 + 0.2,
            duration: Math.random() * 4 + 3,
            repeat: -1,
            delay: Math.random() * 2,
            ease: 'none',
            yoyo: true
        });
    }
}

function _dismissSplash() {
    return new Promise(resolve => {
        const splash = document.getElementById('guild-splash');
        const app = document.getElementById('app-container');
        if (!splash) { resolve(); return; }
        if (typeof gsap !== 'undefined' && !document.hidden) {
            // Kill ALL infinite tweens from the splash sigil animation (motes, star rotation)
            document.querySelectorAll('.splash-mote').forEach(m => { gsap.killTweensOf(m); m.remove(); });
            gsap.killTweensOf('#splash-star, #splash-ring-outer, #splash-ring-inner, #splash-eye, #splash-pupil');

            const tl = gsap.timeline({ onComplete: () => {
                splash.remove();
                document.body.style.overflow = '';
                resolve();
            }});
            // Flash the sigil bright
            tl.to('#splash-sigil', { filter: 'drop-shadow(0 0 80px rgba(178,70,242,0.9)) brightness(2)', scale: 1.2, duration: 0.4, ease: 'power2.in' }, 0);
            tl.to('#splash-title', { opacity: 0, y: -20, duration: 0.3 }, 0.1);
            tl.to('#splash-status, #splash-bar-track', { opacity: 0, duration: 0.2 }, 0.1);
            // White flash
            tl.to(splash, { backgroundColor: 'rgba(178,70,242,0.15)', duration: 0.15 }, 0.4);
            // Fade out splash
            tl.to(splash, { opacity: 0, duration: 0.5, ease: 'power2.in' }, 0.5);
            // Reveal app
            tl.to(app, { opacity: 1, y: 0, duration: 0.8, ease: 'power3.out' }, 0.6);
        } else {
            splash.style.display = 'none';
            app.style.opacity = '1';
            app.style.transform = 'none';
            document.body.style.overflow = '';
            resolve();
        }
    });
}

// ═══════════════════════════════════════════════════════════════════════
//  GSAP Magical Effects — sprinkled throughout the UI
// ═══════════════════════════════════════════════════════════════════════

function _guildRevealSidebar() {
    _sidebarRevealed = true;  // Set immediately so re-renders produce visible cards
    const cards = document.querySelectorAll('.character-card');
    if (typeof gsap === 'undefined' || document.hidden) {
        // No GSAP or tab backgrounded — reveal instantly
        cards.forEach(c => { c.classList.add('revealed'); c.style.opacity = '1'; c.style.transform = 'none'; });
        return;
    }
    // Stagger-reveal all character cards
    gsap.fromTo(cards,
        { opacity: 0, x: -30, scale: 0.95 },
        { opacity: 1, x: 0, scale: 1, duration: 0.5, stagger: 0.06, ease: 'back.out(1.4)',
          onComplete: () => cards.forEach(c => c.classList.add('revealed'))
        }
    );
    // Sidebar title entrance
    gsap.fromTo('.sidebar-header h2',
        { opacity: 0, y: -10, letterSpacing: '8px' },
        { opacity: 1, y: 0, letterSpacing: '1.5px', duration: 0.8, ease: 'power3.out' }
    );
}

function _spellCastFlash() {
    // Full-screen arcane flash when sending a message
    if (typeof gsap === 'undefined') return;
    let flash = document.getElementById('spell-flash');
    if (!flash) {
        flash = document.createElement('div');
        flash.id = 'spell-flash';
        document.body.appendChild(flash);
    }
    gsap.fromTo(flash, { opacity: 0.6 }, { opacity: 0, duration: 0.8, ease: 'power2.out' });
    // Send button charge
    const btn = document.getElementById('send-btn');
    if (btn) {
        gsap.fromTo(btn, { scale: 1.4, rotation: -15 }, { scale: 1, rotation: 0, duration: 0.6, ease: 'elastic.out(1, 0.4)' });
    }
}

function _avatarSelectBurst(avatarEl) {
    if (typeof gsap === 'undefined' || !avatarEl) return;
    // Ripple burst on the active avatar
    gsap.fromTo(avatarEl,
        { boxShadow: '0 0 0 0 rgba(178,70,242,0.7)' },
        { boxShadow: '0 0 0 20px rgba(178,70,242,0)', duration: 0.7, ease: 'power2.out' }
    );
    gsap.fromTo(avatarEl, { scale: 1.15 }, { scale: 1, duration: 0.5, ease: 'elastic.out(1, 0.5)' });
}

function _messageEntrance(msgEl) {
    // Bubble entrance: spring overshoot slide-in + a 6-particle
    // sparkle burst. Earlier rounds blamed this for the screen flash
    // and stripped it out, but the actual culprit was the body-wide
    // brightness fromTo in applyGlobalBackground that fired every poll
    // tick. With that removed (commit dd5eab5), the per-bubble GSAP
    // is harmless and the user wants the polish back.
    if (typeof gsap === 'undefined' || !msgEl) return;
    const isUser = msgEl.classList.contains('user-message');
    gsap.fromTo(msgEl,
        { opacity: 0, y: 30, x: isUser ? 40 : -40, scale: 0.9 },
        { opacity: 1, y: 0, x: 0, scale: 1, duration: 0.6, ease: 'back.out(1.2)' }
    );
    // Tiny sparkles around the new message — radial burst from the
    // bubble centre, fading out over 0.6s with a small per-particle
    // stagger so it reads as a sparkle trail rather than one pop.
    const bubble = msgEl.querySelector('.bubble');
    if (bubble) {
        for (let i = 0; i < 6; i++) {
            const spark = document.createElement('div');
            spark.className = 'msg-sparkle';
            bubble.appendChild(spark);
            const angle = (i / 6) * Math.PI * 2;
            gsap.fromTo(spark,
                { x: 0, y: 0, opacity: 1, scale: 1 },
                { x: Math.cos(angle) * 40, y: Math.sin(angle) * 40,
                  opacity: 0, scale: 0,
                  duration: 0.6, delay: i * 0.05, ease: 'power2.out',
                  onComplete: () => spark.remove()
                }
            );
        }
    }
}

function _typingIndicatorMagic(el) {
    if (typeof gsap === 'undefined' || !el) return;
    // Orbiting glow around typing indicator
    gsap.to(el, {
        boxShadow: '0 0 20px rgba(178,70,242,0.4), 0 0 40px rgba(108,99,255,0.2)',
        duration: 1.5, repeat: -1, yoyo: true, ease: 'sine.inOut'
    });
}

function _enchantButton(btn) {
    if (typeof gsap === 'undefined' || !btn) return;
    btn.addEventListener('mouseenter', () => {
        gsap.to(btn, { scale: 1.05, duration: 0.2, ease: 'power2.out' });
        gsap.to(btn, { boxShadow: '0 0 20px var(--accent-glow)', duration: 0.3 });
    });
    btn.addEventListener('mouseleave', () => {
        gsap.to(btn, { scale: 1, duration: 0.3, ease: 'elastic.out(1, 0.5)' });
        gsap.to(btn, { boxShadow: 'none', duration: 0.5 });
    });
}

function _initMagicalEffects() {
    if (typeof gsap === 'undefined') return;
    // Enchant header action buttons
    document.querySelectorAll('.chat-header-actions button').forEach(_enchantButton);
    _enchantButton(document.getElementById('settings-btn'));
    _enchantButton(document.getElementById('send-btn'));

    // Ambient rune watermark in chat
    const chatStream = document.getElementById('chat-stream');
    if (chatStream && !document.getElementById('chat-rune-watermark')) {
        const rune = document.createElement('div');
        rune.id = 'chat-rune-watermark';
        rune.innerHTML = '<svg viewBox="0 0 200 200"><polygon points="100,10 123,72 190,72 135,112 155,175 100,140 45,175 65,112 10,72 77,72" fill="none" stroke="rgba(178,70,242,0.5)" stroke-width="1"/><circle cx="100" cy="100" r="85" fill="none" stroke="rgba(178,70,242,0.3)" stroke-width="0.5"/></svg>';
        chatStream.style.position = 'relative';
        chatStream.appendChild(rune);
        gsap.to(rune, { rotation: 360, duration: 120, repeat: -1, ease: 'none' });
        gsap.to(rune, { opacity: 0.06, duration: 4, repeat: -1, yoyo: true, ease: 'sine.inOut' });
    }

    // Particle system boost — add mouse-interactive arcane trails
    const canvas = document.getElementById('magic-particles');
    if (canvas) {
        canvas.addEventListener('mousemove', (e) => {
            if (typeof _spawnMouseParticle === 'function') _spawnMouseParticle(e.clientX, e.clientY);
        });
    }

    // Floating arcane runes drifting up the sidebar
    _spawnFloatingRunes();

    // Chat input focus glow pulse
    const input = document.getElementById('chat-input');
    if (input) {
        input.addEventListener('focus', () => {
            gsap.fromTo(input, { boxShadow: '0 0 0px rgba(178,70,242,0)' },
                { boxShadow: '0 0 25px rgba(178,70,242,0.2)', duration: 0.5, ease: 'power2.out' });
        });
    }
}

// ── Floating Arcane Runes ──
const _RUNE_GLYPHS = ['\u16A0','\u16A2','\u16A6','\u16A8','\u16B1','\u16B7','\u16C1','\u16C7','\u16D2','\u16D6','\u16DA','\u16DE','\u16DF','\u2638','\u2720','\u2721','\u269D','\u2694','\u2604'];

function _spawnFloatingRunes() {
    if (typeof gsap === 'undefined') return;
    const sidebar = document.getElementById('sidebar');
    if (!sidebar) return;
    // Spawn a new rune every 2-4 seconds
    setInterval(() => {
        if (document.hidden) return; // pause when tab not visible
        const rune = document.createElement('div');
        rune.className = 'magic-rune';
        rune.textContent = _RUNE_GLYPHS[Math.floor(Math.random() * _RUNE_GLYPHS.length)];
        const rect = sidebar.getBoundingClientRect();
        rune.style.left = (rect.left + Math.random() * rect.width) + 'px';
        rune.style.top = (rect.bottom + 10) + 'px';
        rune.style.fontSize = (14 + Math.random() * 10) + 'px';
        document.body.appendChild(rune);
        gsap.to(rune, {
            y: -(rect.height + 40), x: (Math.random() - 0.5) * 60,
            rotation: (Math.random() - 0.5) * 180,
            opacity: Math.random() * 0.25 + 0.1,
            duration: 6 + Math.random() * 4,
            ease: 'none',
            onComplete: () => rune.remove()
        });
        // Fade in then out
        gsap.fromTo(rune, { opacity: 0 }, { opacity: Math.random() * 0.25 + 0.1, duration: 1, ease: 'power1.in' });
        gsap.to(rune, { opacity: 0, duration: 1.5, delay: 5 + Math.random() * 3, ease: 'power1.out' });
    }, 2000 + Math.random() * 2000);
}

// ── Generation Spellcasting Circle Overlay ──
function _showGenerationCircle(label) {
    if (typeof gsap === 'undefined') return;
    let ov = document.getElementById('generation-circle-overlay');
    if (!ov) {
        ov = document.createElement('div');
        ov.id = 'generation-circle-overlay';
        ov.innerHTML = `
            <svg viewBox="0 0 200 200">
                <circle cx="100" cy="100" r="90" fill="none" stroke="rgba(178,70,242,0.5)" stroke-width="1"
                    stroke-dasharray="565" stroke-dashoffset="565" id="gen-circle-outer"/>
                <circle cx="100" cy="100" r="70" fill="none" stroke="rgba(108,99,255,0.4)" stroke-width="0.8"
                    stroke-dasharray="440" stroke-dashoffset="440" id="gen-circle-inner"/>
                <polygon points="100,20 132,68 180,80 145,115 155,165 100,140 45,165 55,115 20,80 68,68"
                    fill="none" stroke="rgba(178,70,242,0.6)" stroke-width="0.8" opacity="0" id="gen-pentagram"/>
                <circle cx="100" cy="100" r="10" fill="rgba(178,70,242,0.3)" opacity="0" id="gen-core"/>
            </svg>
            <div class="gen-status" id="gen-status-text">${label || 'Channeling arcane energies...'}</div>`;
        document.body.appendChild(ov);
    } else {
        const st = ov.querySelector('.gen-status');
        if (st) st.textContent = label || 'Channeling arcane energies...';
    }
    ov.style.pointerEvents = 'none';
    const tl = gsap.timeline();
    tl.to(ov, { opacity: 1, duration: 0.4 }, 0);
    tl.to('#gen-circle-outer', { strokeDashoffset: 0, duration: 1.5, ease: 'power2.inOut' }, 0);
    tl.to('#gen-circle-inner', { strokeDashoffset: 0, duration: 1.2, ease: 'power2.inOut' }, 0.3);
    tl.to('#gen-pentagram', { opacity: 0.7, duration: 0.6 }, 0.8);
    tl.to('#gen-pentagram', { rotation: 360, duration: 12, ease: 'none', repeat: -1, transformOrigin: '100px 100px' }, 0.8);
    tl.to('#gen-core', { opacity: 0.8, scale: 1.5, duration: 0.8, yoyo: true, repeat: -1, ease: 'sine.inOut', transformOrigin: '100px 100px' }, 1.2);
}

function _hideGenerationCircle() {
    if (typeof gsap === 'undefined') return;
    const ov = document.getElementById('generation-circle-overlay');
    if (!ov) return;
    gsap.to(ov, { opacity: 0, duration: 0.5, ease: 'power2.in', onComplete: () => ov.remove() });
    // Burst particles from center
    _completionBurst();
}

function _completionBurst() {
    if (typeof gsap === 'undefined') return;
    const cx = window.innerWidth / 2, cy = window.innerHeight / 2;
    for (let i = 0; i < 30; i++) {
        const p = document.createElement('div');
        p.className = 'completion-particle';
        p.style.left = cx + 'px';
        p.style.top = cy + 'px';
        document.body.appendChild(p);
        const angle = (i / 30) * Math.PI * 2;
        const dist = 80 + Math.random() * 150;
        gsap.to(p, {
            x: Math.cos(angle) * dist,
            y: Math.sin(angle) * dist,
            opacity: 0, scale: 0,
            duration: 0.8 + Math.random() * 0.4,
            ease: 'power2.out',
            onComplete: () => p.remove()
        });
    }
}

// ═══════════════════════════════════════════════════════════════════════
//  Boot — splash → server wait → initialize → reveal
// ═══════════════════════════════════════════════════════════════════════

(async function boot() {
    // Disable lag smoothing so animations catch up instantly if tab is backgrounded
    if (typeof gsap !== 'undefined') gsap.ticker.lagSmoothing(0);
    _animateSplashSigil();
    const ready = await _waitForServer(30000);
    const status = document.getElementById('splash-status');
    if (!ready) {
        if (status) status.textContent = 'Server is taking long... loading anyway';
        await new Promise(r => setTimeout(r, 1000));
    }
    await initialize();
    await _dismissSplash();
    _guildRevealSidebar();
    _initMagicalEffects();

    // If tab was backgrounded during boot, re-run visual effects when it becomes visible
    if (document.hidden) {
        const _onFirstVisible = () => {
            if (!document.hidden) {
                document.removeEventListener('visibilitychange', _onFirstVisible);
                _guildRevealSidebar();
                _initMagicalEffects();
            }
        };
        document.addEventListener('visibilitychange', _onFirstVisible);
    }
})();

// ═══════════════════════════════════════════════════════════════════════
//  Theme Management — apply/remove Spellcaster theme to GIMP & Darktable
// ═══════════════════════════════════════════════════════════════════════
async function applyThemeSettings() {
    const gimpToggle = document.getElementById('theme-gimp-toggle');
    const dtToggle = document.getElementById('theme-darktable-toggle');
    const statusEl = document.getElementById('theme-status');
    const btn = document.getElementById('theme-apply-btn');

    btn.disabled = true;
    btn.textContent = 'Applying...';
    statusEl.style.display = 'block';
    statusEl.style.color = '#aaa';
    statusEl.textContent = 'Installing theme files...';

    try {
        const res = await fetch('/api/apply_theme', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                gimp: gimpToggle.checked,
                darktable: dtToggle.checked,
            }),
        });
        const data = await res.json();
        if (data.ok) {
            statusEl.style.color = '#2ed573';
            statusEl.textContent = data.message || 'Theme applied! Restart GIMP/Darktable to see changes.';
        } else {
            statusEl.style.color = '#ff4757';
            statusEl.textContent = data.error || 'Failed to apply theme.';
        }
    } catch (err) {
        statusEl.style.color = '#ff4757';
        statusEl.textContent = 'Network error: ' + err.message;
    }
    btn.disabled = false;
    btn.textContent = 'Apply Theme Settings';
}