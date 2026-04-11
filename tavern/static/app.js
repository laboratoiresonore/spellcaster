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
const stDot = document.getElementById('st-dot');
const stStatus = document.getElementById('st-status');
const bridgeDot = document.getElementById('bridge-dot');
const bridgeStatus = document.getElementById('bridge-status');

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
let llmMode = 'local';  // 'local' (KoboldAI) or 'horde' (AI Horde)

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
        // Direct KoboldAI v1 call
        const res = await fetch(`${koboldUrl}/api/v1/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params)
        });
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
    // This syncs server-side generated avatars/animations into localStorage
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

            // Apply to character in memory
            if (assetUrls.avatar_url && !char.avatar_url) {
                char.avatar_url = assetUrls.avatar_url;
                synced++;
            }
            if (assetUrls.animated_url && !char.animated_url) {
                char.animated_url = assetUrls.animated_url;
                synced++;
            }

            // Persist to localStorage
            if (assetUrls.avatar_url || assetUrls.animated_url) {
                savedIdentities[charId] = savedIdentities[charId] || {};
                if (assetUrls.avatar_url)
                    savedIdentities[charId].avatar_url = savedIdentities[charId].avatar_url || assetUrls.avatar_url;
                if (assetUrls.animated_url)
                    savedIdentities[charId].animated_url = savedIdentities[charId].animated_url || assetUrls.animated_url;
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

        // Merge into localStorage — server is authoritative for keys it has
        let local = JSON.parse(localStorage.getItem('guild_identities') || '{}');
        let synced = 0;
        for (const [charId, srvData] of Object.entries(serverIds)) {
            if (!local[charId]) {
                local[charId] = srvData;
                synced++;
            } else {
                // Server fills in any gaps the local store is missing
                for (const key of ['name', 'personality', 'avatar_url', 'animated_url']) {
                    if (srvData[key] && !local[charId][key]) {
                        local[charId][key] = srvData[key];
                        synced++;
                    }
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

async function checkComfyConnection() {
    try {
        const testRes = await fetch('/api/comfy_status');
        const data = await testRes.json();
        if(data.connected) {
            comfyDot.className = "dot green";
            comfyStatus.textContent = "ComfyUI: Connected";
        } else {
            comfyDot.className = "dot red";
            comfyStatus.textContent = "ComfyUI: Disconnected";
        }
    } catch(e) {
        comfyDot.className = "dot red";
        comfyStatus.textContent = "ComfyUI: Disconnected";
    }
}

async function checkSillyTavernConnection() {
    try {
        const testRes = await fetch('/api/sillytavern_status');
        const data = await testRes.json();
        if(data.connected) {
            stDot.className = "dot green";
            stStatus.textContent = "SillyTavern: Connected";
        } else {
            stDot.className = "dot red";
            stStatus.textContent = "SillyTavern: Disconnected";
        }
    } catch(e) {
        stDot.className = "dot red";
        stStatus.textContent = "SillyTavern: Disconnected";
    }
}

async function checkSignalBridgeConnection() {
    try {
        const testRes = await fetch('/api/signal_bridge_status');
        const data = await testRes.json();
        if(data.connected) {
            bridgeDot.className = "dot green";
            bridgeStatus.textContent = "Signal Bridge: Connected";
        } else {
            bridgeDot.className = "dot red";
            bridgeStatus.textContent = "Signal Bridge: Disconnected";
        }
    } catch(e) {
        bridgeDot.className = "dot red";
        bridgeStatus.textContent = "Signal Bridge: Disconnected";
    }
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
        // Show persistent privacy banner when in horde mode
        _updatePrivacyBanner();
    } catch(e) {
        console.log('Could not fetch server config, using defaults');
    }
    koboldUrlInput.value = koboldUrl;
    comfyUrlInput.value = comfyUrl;
    stUrlInput.value = stUrl;
    bridgeUrlInput.value = bridgeUrl;

    // Check connections
    checkComfyConnection();
    checkSillyTavernConnection();
    checkSignalBridgeConnection();
    setInterval(checkComfyConnection, 30000);
    setInterval(checkSillyTavernConnection, 30000);
    setInterval(checkSignalBridgeConnection, 30000);

    // Check if video models available (for Animate All button)
    checkVideoModelAvailable();

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

    // Load saved identities (localStorage overrides server defaults)
    let savedIdentities = JSON.parse(localStorage.getItem('guild_identities') || '{}');
    characters.forEach(char => {
        if(savedIdentities[char.id]) {
            char.name = savedIdentities[char.id].name || char.name;
            char.personality = savedIdentities[char.id].personality || char.personality;
            char.avatar_url = savedIdentities[char.id].avatar_url || char.avatar_url;
            char.animated_url = savedIdentities[char.id].animated_url || char.animated_url;
        }
    });

    applyGlobalBackground();
    renderSidebar();

    // Check LLM Connection & generate names
    await checkLlmAndGenerateNames();

    // First Time Global Generation (Avatars + Background)
    // Skip if server already generated assets during installation
    const hasServerAssets = characters.some(c => c.avatar_url);
    if (!localStorage.getItem('guild_setup_complete') && !hasServerAssets) {
        await runFirstTimeSetup();
    } else {
        if (hasServerAssets && !localStorage.getItem('guild_setup_complete')) {
            // Server did the work — mark setup as complete
            localStorage.setItem('guild_setup_complete', 'true');
        }
        // Generate avatars for any NEW wizards that don't have one yet
        await generateMissingAvatars();
    }

    // Select first by default
    if (characters.length > 0) {
        selectCharacter(characters[0].id);
    }
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
            const testRes = await fetch(`${koboldUrl}/api/v1/model`);
            if(testRes.ok) {
                llmDot.className = "dot green";
                llmStatus.textContent = "LLM: Connected";
                await generateNamesForCharacters();
            } else { throw new Error("Bad response"); }
        }
    } catch(e) {
        llmDot.className = "dot red";
        llmStatus.textContent = "LLM: Disconnected";
    }
}

async function generateNamesForCharacters() {
    // If a character name is Unnamed Wizard, prompt the LLM to rename it
    // Studio characters already have proper names — skip them
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
        if(char.name === "Unnamed Wizard") {
            let context = `Context: We are naming magical avatars.\nCommand: Invent a single, very short, creative fantasy name (e.g. Zephyr) for a wizard specializing in: ${char.subtext}. Do NOT use titles like 'Master of'.\nName:`;
            try {
                const data = await llmGenerate({ prompt: context, max_length: 15, temperature: 0.8, stop_sequence: ["\n", "."] });
                let llmName = data.results[0].text.trim().replace(/["']/g, '');
                if(llmName) char.name = llmName;
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
        } else {
            btn.disabled = true;
            btn.title = 'No video model detected in ComfyUI (needs WAN, LTX, SVD, or CogVideo)';
        }
    } catch(e) {
        btn.disabled = true;
        btn.title = 'Cannot check for video models — ComfyUI may be offline';
    }
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

async function queueAnimatedAvatars() {
    // Find characters that have a static avatar but no animated one
    let savedIdentities = JSON.parse(localStorage.getItem('guild_identities') || '{}');
    const needsAnimation = characters.filter(c => {
        const saved = savedIdentities[c.id];
        const hasStatic = c.avatar_url || saved?.avatar_url;
        const hasAnimated = c.animated_url || saved?.animated_url;
        return hasStatic && !hasAnimated;
    });

    if (needsAnimation.length === 0) return;

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
    if(bgUrl) {
        document.body.style.backgroundImage = `url('${bgUrl}')`;
        document.body.style.backgroundSize = "cover";
        document.body.style.backgroundPosition = "center";
        document.body.style.backgroundRepeat = "no-repeat";
        document.body.style.backgroundAttachment = "fixed";
        // Magical transition when background changes
        if (typeof gsap !== 'undefined') {
            gsap.fromTo(document.body, { filter: 'brightness(1.5) saturate(1.5)' },
                { filter: 'brightness(1) saturate(1)', duration: 1.5, ease: 'power2.out' });
        }
    }
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
    };
    let savedIdentities = JSON.parse(localStorage.getItem('guild_identities') || '{}');
    savedIdentities[char.id] = identity;
    localStorage.setItem('guild_identities', JSON.stringify(savedIdentities));
    // Persist to server (fire-and-forget)
    fetch('/api/wizard_identities', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({identities: {[char.id]: identity}}),
    }).catch(() => {});
}

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
        const avatarUrl = char.avatar_url || `/api/avatar/${char.id}`;

        if (char.animated_url) {
            card.innerHTML = `
                <div class="avatar avatar-animated" style="background: ${gradient};">
                    <video src="${char.animated_url}" autoplay loop muted playsinline></video>
                </div>
                <div class="character-info">
                    <h3>${char.name}</h3>
                    <p>${char.subtext}</p>
                </div>
            `;
        } else {
            card.innerHTML = `
                <div class="avatar" style="background: ${gradient}; background-image: url('${avatarUrl}');"></div>
                <div class="character-info">
                    <h3>${char.name}</h3>
                    <p>${char.subtext}</p>
                </div>
            `;
        }

        card.addEventListener('click', () => { selectCharacter(char.id); onMobileCharacterSelect(); });

        // ── Wizard info tooltip on hover ──
        let hoverTimer = null;
        card.addEventListener('mouseenter', () => {
            hoverTimer = setTimeout(() => showWizardTooltip(char, card), 420);
        });
        card.addEventListener('mouseleave', () => {
            clearTimeout(hoverTimer);
            hideWizardTooltip();
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

    // Add separator if there are both core and model wizards (and filter allows model results)
    if (modelChars.length > 0) {
        const hasVisibleModels = modelChars.some(c =>
            !filter || c.name.toLowerCase().includes(lowFilter) || c.subtext.toLowerCase().includes(lowFilter)
        );
        if (hasVisibleModels && coreChars.length > 0) {
            const sep = document.createElement('div');
            sep.className = 'sidebar-separator';
            sep.innerHTML = '<span>Per-Model Wizards</span>';
            characterList.appendChild(sep);
        }
    }

    modelChars.forEach(renderCard);
}

searchInput.addEventListener('input', (e) => {
    renderSidebar(e.target.value);
});

// ── Wizard Info Tooltip ──────────────────────────────────────────

let _wizardTooltip = null;
let _tooltipCache = {};  // Cache fetched info to avoid re-fetching

function hideWizardTooltip() {
    if (_wizardTooltip) {
        _wizardTooltip.remove();
        _wizardTooltip = null;
    }
}

async function showWizardTooltip(char, cardEl) {
    hideWizardTooltip();

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

    // Model info
    let modelHtml = '';
    if (info.model_name) {
        const shortModel = info.model_name.split(/[/\\]/).pop();
        modelHtml = `<div class="wt-section">
            <div class="wt-section-label">Model</div>
            <div class="wt-model-row">
                <span class="wt-model-name" title="${info.model_name}">${shortModel}</span>
                <span class="wt-arch-badge">${info.model_arch}</span>
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
        personHtml = `<div class="wt-section"><div class="wt-section-label">Personality</div><div class="wt-personality">${info.personality}</div></div>`;
    }

    tooltip.innerHTML = `
        <div class="wt-header" style="background: ${gradient};">
            <img class="wt-avatar" src="${avatarUrl}" alt="" onerror="this.style.display='none'"/>
            <div class="wt-header-text">
                <div class="wt-name">${info.name}</div>
                <div class="wt-subtext">${info.subtext}</div>
                <span class="wt-badge ${catClass}">${catLabel}</span>
            </div>
        </div>
        ${personHtml}
        ${modelHtml}
        ${fnHtml}
        ${loraHtml}
        ${settingsHint}
    `;

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

function selectCharacter(id) {
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
    
    // Initial greeting — studio characters get a tool-aware intro
    let intro;
    if (char.type === "studio") {
        intro = `Greetings. I am ${char.name}, the Guild's specialist in ${char.subtext}. Describe what you need, and I shall present my tools for you to choose from.`;
    } else {
        intro = `Greetings. I am ${char.name}, master of ${char.subtext}. Tell me what you wish to conjure, and I shall guide your spellcraft.`;
    }
    chatHistory.push({ role: 'assistant', content: intro });
    addAIMessage(intro);

    // GSAP: burst effect on avatar selection
    _avatarSelectBurst(activeAvatar);
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

function addAIMessage(text) {
    const msg = document.createElement('div');
    msg.className = 'message ai-message';

    const { prose, options } = _parseNumberedOptions(text);

    let bubbleHTML = '';
    if (prose) {
        bubbleHTML += `<p>${prose}</p>`;
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
}

function addUserMessage(text) {
    const msg = document.createElement('div');
    msg.className = 'message user-message';
    msg.innerHTML = `
        <div class="avatar-small">${USER_SPARKLE_SVG}</div>
        <div class="bubble"><p>${text}</p></div>
    `;
    chatStream.appendChild(msg);
    chatStream.scrollTop = chatStream.scrollHeight;
    _messageEntrance(msg);
}

function addSystemMessage(htmlContent) {
    const msg = document.createElement('div');
    msg.className = 'message ai-message';
    msg.innerHTML = `
        <div class="avatar-small comfyui-logo">${COMFYUI_LOGO_SVG}</div>
        <div class="bubble system-bubble"><p>${htmlContent}</p></div>
    `;
    chatStream.appendChild(msg);
    chatStream.scrollTop = chatStream.scrollHeight;
    _messageEntrance(msg);
}

async function askKobold(text) {
    sendBtn.disabled = true;
    addTypingIndicator();
    chatHistory.push({ role: 'user', content: text });

    const char = characters.find(c => c.id === activeCharacterId);

    // Fetch per-character system prompt if available, else use global
    let charPrompt = systemPrompt;
    if (char && char.id) {
        try {
            const cpRes = await fetch(`/api/system_prompt/${char.id}`);
            const cpData = await cpRes.json();
            if (cpData.prompt) charPrompt = cpData.prompt;
        } catch(e) { /* fallback to global */ }
    }

    // Build the mega prompt
    let context = `${charPrompt}\n\nYour Persona:\nYou are ${char.name}, a magical expert in ${char.subtext}.\n${char.personality || ''}\n\n`;
    for(let h of chatHistory) {
        context += `${h.role === 'user' ? 'User' : 'Assistant'}: ${h.content}\n`;
    }
    context += "Assistant: ";

    try {
        // Warn in chat on first horde message per session
            if (llmMode === 'horde' && !window._hordeWarnShown) {
                addSystemMessage(
                    '\u26a0 <strong>Horde Mode Active</strong> — Your message is being sent to ' +
                    'volunteer workers on the AI Horde network. <strong>Do not share personal or sensitive info.</strong>'
                );
                window._hordeWarnShown = true;
            }

            const data = await llmGenerate({
                prompt: context,
                max_context_length: 4096,
                max_length: 300,
                temperature: 0.7,
                stop_sequence: ["User:", "\nUser"]
            });
        let aiReply = data.results[0].text.trim();
        
        chatHistory.push({ role: 'assistant', content: aiReply });

        // Did the AI output a JSON payload to execute?
        const jsonMatch = aiReply.match(/```json\n([\s\S]*?)\n```/);
        
        if (jsonMatch) {
            // Strip the JSON out so the bubble just shows the conversational text array
            const cleanText = aiReply.replace(jsonMatch[0], '').trim();
            if (cleanText) addAIMessage(cleanText);

            const payloadStr = jsonMatch[1];
            addSystemMessage(`<strong>Spell Succeeded!</strong><br>Executing JSON Workflow payload...`);
            
            // Dispatch to python backend for comfy execution
            dispatchToComfy(JSON.parse(payloadStr));
        } else {
            addAIMessage(aiReply);
        }

    } catch (err) {
        addAIMessage(`[Error: Could not connect to LLM at ${koboldUrl}. Click Settings to configure.]`);
        console.error(err);
    }

    removeTypingIndicator();
    sendBtn.disabled = false;
}

async function dispatchToComfy(payload) {
    try {
        payload.comfy_url = comfyUrl; // Intercept and attach user's Comfy URL natively
        payload.char_id = activeCharacterId; // Tell the server which wizard is requesting
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
        if (data.type === 'images' && data.urls && data.urls.length) {
            const imgs = data.urls.map(u => `<img src="${u}" class="generated-image" style="max-width:100%;border-radius:8px;margin:4px 0;">`).join('');
            addSystemMessage(`<strong>Spell Complete!</strong><br>${imgs}`);
        } else if (data.type === 'videos' && data.urls && data.urls.length) {
            const vids = data.urls.map(u => `<video src="${u}" controls autoplay loop muted style="max-width:100%;border-radius:8px;margin:4px 0;"></video>`).join('');
            addSystemMessage(`<strong>Spell Complete!</strong><br>${vids}`);
        } else if (data.mock_img) {
            addSystemMessage(`<strong>Image Rendered!</strong><br><img src="${data.mock_img}" class="generated-image">`);
        } else {
            addSystemMessage(`<strong>Spell Complete!</strong><br>Result: ${JSON.stringify(data).substring(0, 200)}`);
        }
    } catch (e) {
        addSystemMessage(`<strong>Spell Failed!</strong><br>${e.message}`);
        console.error(e);
    }
}

sendBtn.addEventListener('click', () => {
    _spellCastFlash();
    const text = chatInput.value.trim();
    if (!text) return;
    addUserMessage(text);
    chatInput.value = '';
    chatInput.style.height = 'auto'; 
    askKobold(text);
});

chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendBtn.click();
    }
});
chatInput.addEventListener('input', function() { this.style.height = 'auto'; this.style.height = (this.scrollHeight) + 'px'; });

resetBtn.addEventListener('click', () => {
    if(activeCharacterId) selectCharacter(activeCharacterId);
});

generateAvatarBtn.addEventListener('click', async () => {
    if(!activeCharacterId) return;
    overlay.classList.remove('hidden');
    document.querySelector('#loading-overlay p').textContent = "Synthesizing Avatar...";
    _showGenerationCircle('Conjuring avatar...');
    try {
        const response = await fetch('/api/avatar_generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: activeCharacterId, comfy_url: comfyUrl })
        });
        const data = await response.json();
        if(data.avatar_url) {
            const char = characters.find(c => c.id === activeCharacterId);
            const refreshUrl = data.avatar_url + "&t=" + new Date().getTime();
            char.avatar_url = refreshUrl;
            saveIdentity(char);
            activeAvatar.style.backgroundImage = `url('${char.avatar_url}')`;
            renderSidebar(searchInput.value);
            addSystemMessage(`<strong>Avatar Updated!</strong><br>Generated new avatar visually representing ${char.subtext}.`);
        }
    } catch(e) {
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
                                const refreshUrl = result.avatar_url + "&t=" + new Date().getTime();
                                char.avatar_url = refreshUrl;
                                char._batch_applied = true;
                                saveIdentity(char);
                                if(char.id === activeCharacterId) {
                                    activeAvatar.style.backgroundImage = `url('${char.avatar_url}')`;
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

// Open modal
summonBtn.addEventListener('click', () => {
    selectedSummonModel = null;
    summonNext.disabled = true;
    summonStep1.style.display = 'block';
    summonStep2.style.display = 'none';
    summonScaffoldSelect.value = 'auto';
    summonModal.classList.remove('hidden');
    loadSummonModels();
});

summonCancel.addEventListener('click', () => {
    summonModal.classList.add('hidden');
});

summonNext.addEventListener('click', () => {
    generateWizardIdentity();
});

summonBack.addEventListener('click', () => {
    summonStep1.style.display = 'block';
    summonStep2.style.display = 'none';
});

summonRegenerate.addEventListener('click', () => {
    generateWizardIdentity();
});

summonCreate.addEventListener('click', async () => {
    if (!selectedSummonModel) return;
    const m = selectedSummonModel;
    const scaffold = summonScaffoldSelect.value === 'auto' ? guessScaffold(m.name, m.arch) : summonScaffoldSelect.value;
    const name = document.getElementById('summon-name-input').value.trim() || 'Unnamed Wizard';
    const personality = document.getElementById('summon-personality-input').value.trim();
    const subtext = document.getElementById('summon-subtext-input').value.trim();

    summonCreate.disabled = true;
    summonCreate.textContent = 'Summoning...';

    try {
        const res = await fetch('/api/summon_wizard', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model_name: m.name,
                model_arch: m.arch,
                model_type: m.type,
                name: name,
                personality: personality,
                subtext: subtext,
                scaffold: scaffold,
            })
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
            addSystemMessage(`<strong>Wizard Summoned!</strong><br>${name} has joined the Guild, wielding the power of <em>${m.name}</em> (${getScaffoldLabel(scaffold)}).`);

            // Auto-generate avatar in background
            try {
                const avatarRes = await fetch('/api/avatar_generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: newChar.id, comfy_url: comfyUrl })
                });
                const aData = await avatarRes.json();
                if (aData.avatar_url) {
                    const refreshUrl = aData.avatar_url + "&t=" + new Date().getTime();
                    newChar.avatar_url = refreshUrl;
                    saveIdentity(newChar);
                    activeAvatar.style.backgroundImage = `url('${newChar.avatar_url}')`;
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

        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:10px 12px;border-bottom:1px solid #222;';
        row.innerHTML = `
            <label style="display:flex;align-items:center;cursor:pointer;flex-shrink:0;">
                <input type="checkbox" data-lora="${lora.name}" ${enabled ? 'checked' : ''}
                    style="width:18px;height:18px;accent-color:#B246F2;cursor:pointer;">
            </label>
            <div style="flex:1;min-width:0;">
                <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                    <span style="font-weight:600;color:#eee;font-size:13px;">${lora.display_name}</span>
                    <span style="font-size:11px;color:#888;">${sourceIcon}</span>
                    ${civitLink}
                </div>
                <p style="color:#aaa;font-size:12px;margin-top:2px;">${purposeText}</p>
                ${lora.description ? `<p style="color:#666;font-size:11px;margin-top:2px;max-height:40px;overflow:hidden;">${lora.description.substring(0, 120)}</p>` : ''}
            </div>
        `;

        const checkbox = row.querySelector('input[type="checkbox"]');
        checkbox.addEventListener('change', () => {
            state[lora.name] = checkbox.checked;
            saveLoraState();
        });

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

    unknownLoras.forEach(lora => {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;margin-bottom:8px;';
        row.innerHTML = `
            <span style="font-weight:600;color:#ddd;font-size:13px;min-width:140px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${lora.name}">${lora.display_name}</span>
            <input type="text" data-lora-name="${lora.name}" placeholder="e.g. hand refinement, anime style..."
                style="flex:1;padding:6px 10px;border-radius:6px;border:1px solid #444;background:#1a1a2e;color:#eee;font-size:12px;">
        `;
        loraInterrogationList.appendChild(row);
    });
}

loraInterrogationSave.addEventListener('click', async () => {
    const inputs = loraInterrogationList.querySelectorAll('input[data-lora-name]');
    const descriptions = {};
    inputs.forEach(inp => {
        const val = inp.value.trim();
        if (val) descriptions[inp.dataset.loraName] = val;
    });

    if (Object.keys(descriptions).length === 0) {
        loraInterrogation.style.display = 'none';
        return;
    }

    try {
        await fetch('/api/lora_describe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ descriptions }),
        });
        // Refresh the LoRA modal
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
    if (typeof gsap === 'undefined' || !msgEl) return;
    const isUser = msgEl.classList.contains('user-message');
    gsap.fromTo(msgEl,
        { opacity: 0, y: 30, x: isUser ? 40 : -40, scale: 0.9 },
        { opacity: 1, y: 0, x: 0, scale: 1, duration: 0.6, ease: 'back.out(1.2)' }
    );
    // Tiny sparkles around the new message
    const bubble = msgEl.querySelector('.bubble');
    if (bubble) {
        for (let i = 0; i < 6; i++) {
            const spark = document.createElement('div');
            spark.className = 'msg-sparkle';
            bubble.appendChild(spark);
            const angle = (i / 6) * Math.PI * 2;
            gsap.fromTo(spark,
                { x: 0, y: 0, opacity: 1, scale: 1 },
                { x: Math.cos(angle) * 40, y: Math.sin(angle) * 40, opacity: 0, scale: 0,
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