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
const llmDot = document.getElementById('llm-dot');
const llmStatus = document.getElementById('llm-status');

// Settings
const settingsBtn = document.getElementById('settings-btn');
const settingsModal = document.getElementById('settings-modal');
const settingsCancel = document.getElementById('settings-cancel');
const settingsSave = document.getElementById('settings-save');
const koboldUrlInput = document.getElementById('kobold-url-input');

// Rename Elements
const renameModal = document.getElementById('rename-modal');
const renameInput = document.getElementById('rename-input');
const renameCancel = document.getElementById('rename-cancel');
const renameSave = document.getElementById('rename-save');
const renameLlmBtn = document.getElementById('rename-llm-btn');

let koboldUrl = localStorage.getItem('kobold_url') || 'http://127.0.0.1:5001';
koboldUrlInput.value = koboldUrl;

let characters = [];
let activeCharacterId = null;
let systemPrompt = "";
let chatHistory = [];

async function initialize() {
    // Fetch System Prompt
    const promptRes = await fetch('/api/system_prompt');
    const promptData = await promptRes.json();
    systemPrompt = promptData.prompt;

    // Fetch Guild Members
    const charRes = await fetch('/api/characters');
    characters = await charRes.json();
    
    // Load saved identities
    let savedIdentities = JSON.parse(localStorage.getItem('guild_identities') || '{}');
    characters.forEach(char => {
        if(savedIdentities[char.id]) {
            char.name = savedIdentities[char.id].name || char.name;
            char.personality = savedIdentities[char.id].personality || char.personality;
            char.avatar_url = savedIdentities[char.id].avatar_url || char.avatar_url;
        }
    });

    applyGlobalBackground();
    renderSidebar();

    // Check LLM Connection & generate names
    await checkLlmAndGenerateNames();

    // First Time Global Generation (Avatars + Background)
    if (!localStorage.getItem('guild_setup_complete')) {
        await runFirstTimeSetup();
    }

    // Select first by default
    if (characters.length > 0) {
        selectCharacter(characters[0].id);
    }
}

async function checkLlmAndGenerateNames() {
    try {
        const testRes = await fetch(`${koboldUrl}/api/v1/model`);
        if(testRes.ok) {
            llmDot.className = "dot green";
            llmStatus.textContent = "LLM: Connected";
            await generateNamesForCharacters();
        } else { throw new Error("Bad response"); }
    } catch(e) {
        llmDot.className = "dot red";
        llmStatus.textContent = "LLM: Disconnected";
    }
}

async function generateNamesForCharacters() {
    // If a character name is Unnamed Wizard, prompt the LLM to rename it
    for(let i=0; i<characters.length; i++) {
        let char = characters[i];
        if(char.name === "Unnamed Wizard") {
            let context = `Context: We are naming magical avatars.\nCommand: Invent a single, very short, creative fantasy name (e.g. Zephyr) for a wizard specializing in: ${char.subtext}. Do NOT use titles like 'Master of'.\nName:`;
            try {
                const response = await fetch(`${koboldUrl}/api/v1/generate`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: context, max_length: 15, temperature: 0.8, stop_sequence: ["\n", "."] })
                });
                const data = await response.json();
                let llmName = data.results[0].text.trim().replace(/["']/g, '');
                if(llmName) char.name = llmName;
                saveIdentity(char);
                renderSidebar(searchInput.value);
                
                // Now generate personality
                let pContext = `Context: A magical avatar named ${char.name} specializes in ${char.subtext}.\nCommand: Write exactly one short, eccentric sentence describing their speaking style and demeanor.\nPersonality:`;
                const pResponse = await fetch(`${koboldUrl}/api/v1/generate`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: pContext, max_length: 60, temperature: 0.8, stop_sequence: ["\n"] })
                });
                const pData = await pResponse.json();
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
    overlay.classList.remove('hidden');
    document.querySelector('#loading-overlay p').textContent = "Initializing First-Time Setup... Generating Avatars...";
    
    // 1. Generate Avatars for everyone
    for(let i=0; i<characters.length; i++) {
        let char = characters[i];
        try {
            const avatarRes = await fetch('/api/avatar_generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: char.id })
            });
            const aData = await avatarRes.json();
            if(aData.avatar_url) {
                char.avatar_url = aData.avatar_url;
                saveIdentity(char);
            }
        } catch(e) { console.error(e); }
    }
    renderSidebar(searchInput.value);

    // 2. Generate a Guild Background using the first character's style
    document.querySelector('#loading-overlay p').textContent = "Synthesizing Guild Background...";
    if(characters.length > 0) {
        try {
            const bgRes = await fetch('/api/background_generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: characters[0].id })
            });
            const bData = await bgRes.json();
            if(bData.bg_url) {
                localStorage.setItem('guild_global_bg', bData.bg_url);
                applyGlobalBackground();
            }
        } catch(e) { console.error(e); }
    }
    
    localStorage.setItem('guild_setup_complete', 'true');
    document.querySelector('#loading-overlay p').textContent = "The Guild is thinking...";
    overlay.classList.add('hidden');
}

function applyGlobalBackground() {
    let bgUrl = localStorage.getItem('guild_global_bg');
    if(bgUrl) {
        document.body.style.backgroundImage = `url('${bgUrl}')`;
        document.body.style.backgroundSize = "cover";
        document.body.style.backgroundPosition = "center";
    }
}

function saveIdentity(char) {
    let savedIdentities = JSON.parse(localStorage.getItem('guild_identities') || '{}');
    savedIdentities[char.id] = {
        name: char.name,
        personality: char.personality,
        avatar_url: char.avatar_url
    };
    localStorage.setItem('guild_identities', JSON.stringify(savedIdentities));
}

function renderSidebar(filter = "") {
    characterList.innerHTML = '';
    const lowFilter = filter.toLowerCase();

    characters.forEach(char => {
        if (filter && !char.name.toLowerCase().includes(lowFilter) && !char.subtext.toLowerCase().includes(lowFilter)) {
            return;
        }

        const card = document.createElement('div');
        card.className = 'character-card';
        if (char.id === activeCharacterId) card.classList.add('active');
        card.dataset.id = char.id;

        // Lazy-load face generation cue!
        const gradient = `linear-gradient(135deg, ${char.color1}, ${char.color2})`;
        const avatarUrl = char.avatar_url || `/api/avatar/${char.id}`;
        
        card.innerHTML = `
            <div class="avatar" style="background: ${gradient}; background-image: url('${avatarUrl}');"></div>
            <div class="character-info">
                <h3>${char.name}</h3>
                <p>${char.subtext}</p>
            </div>
        `;

        card.addEventListener('click', () => selectCharacter(char.id));
        characterList.appendChild(card);
    });
}

searchInput.addEventListener('input', (e) => {
    renderSidebar(e.target.value);
});

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

    // Reset Chat Memory
    chatHistory = [];
    chatStream.innerHTML = '';
    
    // Initial greeting
    const intro = `Greetings. I am ${char.name}, master of ${char.subtext}. Tell me what you wish to conjure, and I shall guide your spellcraft.`;
    chatHistory.push({ role: 'assistant', content: intro });
    addAIMessage(intro);
}

function addAIMessage(text) {
    const msg = document.createElement('div');
    msg.className = 'message ai-message';
    msg.innerHTML = `
        <div class="avatar-small" style="${activeAvatar.style.cssText}"></div>
        <div class="bubble"><p>${text}</p></div>
    `;
    chatStream.appendChild(msg);
    chatStream.scrollTop = chatStream.scrollHeight;
}

function addUserMessage(text) {
    const msg = document.createElement('div');
    msg.className = 'message user-message';
    msg.innerHTML = `
        <div class="avatar-small"></div>
        <div class="bubble"><p>${text}</p></div>
    `;
    chatStream.appendChild(msg);
    chatStream.scrollTop = chatStream.scrollHeight;
}

function addSystemMessage(htmlContent) {
    const msg = document.createElement('div');
    msg.className = 'message ai-message';
    msg.innerHTML = `
        <div class="avatar-small" style="background: transparent; border: 2px solid var(--accent)"></div>
        <div class="bubble" style="background: rgba(178, 70, 242, 0.1); border-color: var(--accent); max-width: 100%;"><p>${htmlContent}</p></div>
    `;
    chatStream.appendChild(msg);
    chatStream.scrollTop = chatStream.scrollHeight;
}

async function askKobold(text) {
    overlay.classList.remove('hidden');
    chatHistory.push({ role: 'user', content: text });

    const char = characters.find(c => c.id === activeCharacterId);

    // Build the mega prompt 
    let context = `${systemPrompt}\n\nYour Persona:\nYou are ${char.name}, a magical expert in ${char.subtext}.\n${char.personality || ''}\n\n`;
    for(let h of chatHistory) {
        context += `${h.role === 'user' ? 'User' : 'Assistant'}: ${h.content}\n`;
    }
    context += "Assistant: ";

    try {
        const response = await fetch(`${koboldUrl}/api/v1/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt: context,
                max_context_length: 4096,
                max_length: 300,
                temperature: 0.7,
                stop_sequence: ["User:", "\nUser"]
            })
        });
        
        const data = await response.json();
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
    
    overlay.classList.add('hidden');
}

async function dispatchToComfy(payload) {
    try {
        const response = await fetch('/api/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        
        if (data.mock_img) {
            addSystemMessage(`<strong>Image Rendered!</strong><br><img src="${data.mock_img}" class="generated-image">`);
        }
    } catch (e) {
        console.error(e);
    }
}

sendBtn.addEventListener('click', () => {
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
    try {
        const response = await fetch('/api/avatar_generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: activeCharacterId })
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
});

generateBgBtn.addEventListener('click', async () => {
    if(!activeCharacterId) return;
    overlay.classList.remove('hidden');
    document.querySelector('#loading-overlay p').textContent = "Synthesizing Background via ComfyUI...";
    try {
        const response = await fetch('/api/background_generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: activeCharacterId })
        });
        const data = await response.json();
        if(data.bg_url) {
            localStorage.setItem('guild_global_bg', data.bg_url);
            applyGlobalBackground();
            addSystemMessage(`<strong>Tavern Remodeled!</strong><br>Generated new background environment.`);
        }
    } catch(e) {
        console.error(e);
    }
    document.querySelector('#loading-overlay p').textContent = "The Guild is thinking...";
    overlay.classList.add('hidden');
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
        const response = await fetch(`${koboldUrl}/api/v1/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: context, max_length: 15, temperature: 0.8, stop_sequence: ["\n", "."] })
        });
        const data = await response.json();
        let llmName = data.results[0].text.trim().replace(/["']/g, '');
        renameInput.value = llmName;
    } catch(e) {
        console.error(e);
        renameInput.value = "Connection Error";
    }
});

// Settings Modal
settingsBtn.addEventListener('click', () => settingsModal.classList.remove('hidden'));
settingsCancel.addEventListener('click', () => settingsModal.classList.add('hidden'));
settingsSave.addEventListener('click', () => {
    koboldUrl = koboldUrlInput.value.trim();
    localStorage.setItem('kobold_url', koboldUrl);
    settingsModal.classList.add('hidden');
});

// Start
initialize();
