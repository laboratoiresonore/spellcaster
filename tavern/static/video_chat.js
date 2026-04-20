/**
 * Video Chat Mode — toggles the Guild chat between normal LLM mode
 * and CinematographerWizard mode.
 *
 * When active:
 *   - Messages route to /api/video/chat instead of the LLM
 *   - The CinematographerWizard's numbered-menu responses render in chat
 *   - Input placeholder changes to indicate video mode
 *   - A visual indicator shows video mode is active
 *
 * Injected after app.js. Hooks into the existing send button.
 */

(function() {
  'use strict';

  let videoChatActive = false;
  const USER_ID = 'guild';  // matches server.py default

  // ── Create the toggle button ──
  const btn = document.createElement('button');
  btn.id = 'video-chat-btn';
  btn.title = 'Toggle Cinematographer Mode';
  btn.innerHTML = '🎬';
  btn.style.cssText = 'background:transparent;border:none;font-size:20px;cursor:pointer;padding:8px;border-radius:50%;transition:all 0.2s;height:40px;width:40px;display:flex;align-items:center;justify-content:center;margin-bottom:2px;opacity:0.5;';

  // Insert before the send button
  const sendBtn = document.getElementById('send-btn');
  const chatInput = document.getElementById('chat-input');
  if (sendBtn && sendBtn.parentNode) {
    sendBtn.parentNode.insertBefore(btn, sendBtn);
  }

  // ── Mode indicator bar ──
  const indicator = document.createElement('div');
  indicator.id = 'video-mode-indicator';
  indicator.style.cssText = 'display:none;background:linear-gradient(90deg,rgba(59,130,246,0.15),rgba(139,92,246,0.15));border-bottom:1px solid rgba(59,130,246,0.3);padding:6px 16px;font-size:12px;color:#93c5fd;text-align:center;font-family:inherit;';
  indicator.innerHTML = '🎬 <strong>Cinematographer Mode</strong> — messages route to the Video Wizard. Click 🎬 again to exit.';
  const chatStream = document.getElementById('chat-stream');
  if (chatStream && chatStream.parentNode) {
    chatStream.parentNode.insertBefore(indicator, chatStream);
  }

  // ── Toggle handler ──
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    videoChatActive = !videoChatActive;

    if (videoChatActive) {
      // Auto-select the Videomancer wizard on activation — the
      // cinematographer mode lives under Videomancer, so the header
      // portrait + active chip should reflect that. Click is a no-op
      // if Videomancer is already active. Using the exported
      // selectCharacter keeps us in sync with the rest of app.js
      // (chat history swap, LoRA refresh, etc.).
      try {
        if (typeof window.selectCharacter === 'function') {
          window.selectCharacter('studio_videomancer');
        } else {
          // Fallback: click the sidebar card directly so the user sees
          // SOMETHING change even if the JS hook isn't exported.
          const card = document.querySelector(
            '[data-id="studio_videomancer"]');
          if (card) card.click();
        }
      } catch (err) { /* non-fatal */ }

      btn.style.opacity = '1';
      btn.style.background = 'rgba(59,130,246,0.2)';
      indicator.style.display = 'block';
      chatInput.placeholder = 'Describe a shot, or type a number to navigate the wizard menu...';
      // R120: server's /api/video/chat 400s on empty text — used to
      // send '' which surfaced as an ugly {"error":"text required"}
      // JSON dump in chat and made the toggle look broken. Send a
      // non-empty trigger so the Cinematographer returns its menu.
      _sendVideoChat('menu');
    } else {
      btn.style.opacity = '0.5';
      btn.style.background = 'transparent';
      indicator.style.display = 'none';
      chatInput.placeholder = 'Just talk to it...';
    }
  });

  // ── Video chat send ──
  async function _sendVideoChat(text) {
    try {
      const res = await fetch('/api/video/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: USER_ID, text: text }),
      });
      const data = await res.json();

      // The wizard returns a dict with "reply" or the response text
      const reply = data.reply || data.text || data.message || JSON.stringify(data);
      if (reply) {
        _addWizardMessage(reply);
      }
    } catch (e) {
      _addWizardMessage('⚠ Video Bridge unavailable. Make sure the server has video support enabled.');
    }
  }

  // ── Cinematographer message renderer ─────────────────────────────
  // The wizard returns plain text whose menus look like:
  //
  //     Pick a WanGP preset:
  //     1. Wan 2.2 Image-to-Video (Lightning) (≥8GB VRAM)
  //     2. ...
  //     17. ...
  //
  // The previous renderer just bolded "1." and dumped the text. With
  // 17 options stacked as plain text it read like dog shit and the
  // user had to type a number to pick. Now we parse the numbered
  // lines into real clickable chips, hoist VRAM tags out of the
  // label into a side badge, and surface a one-click "📎 Attach
  // reference" affordance for the prompts that ask for a ref image.
  // Number-typing still works (the chip click just fires the same
  // _sendVideoChat the user would have typed).

  function _wcEsc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Pull "(≥12GB VRAM)" or "(>=10 GB VRAM)" out of the label, return
  // {clean, badge}. Badge stays null when the option doesn't have one.
  const _VRAM_RE = /\s*\((?:≥|>=)\s*(\d+(?:\.\d+)?)\s*GB\s*VRAM\)\s*$/i;
  function _splitVramBadge(label) {
    const m = label.match(_VRAM_RE);
    if (!m) return { clean: label.trim(), badge: null, vramGb: null };
    return {
      clean: label.replace(_VRAM_RE, '').trim(),
      badge: '≥' + m[1] + ' GB',
      vramGb: parseFloat(m[1]),
    };
  }

  // Local VRAM hint (set by app.js's checkComfyConnection poll). We
  // only use it to dim chips above the user's headroom — never to
  // block selection.
  function _localVramGb() {
    try {
      const total = (window._vramStats && window._vramStats.total_gb) ||
                    (window.comfyStats && window.comfyStats.system &&
                     (window.comfyStats.system.vram_total / 1073741824));
      return typeof total === 'number' ? total : null;
    } catch (e) { return null; }
  }

  // Parse the wizard's text into prose + ordered options.
  function _parseWizardOptions(text) {
    const lines = (text || '').split('\n');
    const proseLines = [];
    const options = [];
    const re = /^\s*(\d+)[.)]\s+(.+)$/;
    for (const ln of lines) {
      const m = ln.match(re);
      if (m) options.push({ num: m[1], rawLabel: m[2].trim() });
      else proseLines.push(ln);
    }
    return { prose: proseLines.join('\n').trim(), options };
  }

  // Detect the "needs a reference image" prompt so we can offer the
  // attach-image button inline. Phrasing comes from
  // scaffold/video_wizard.py — keep this regex broad enough to survive
  // tweaks to the copy.
  const _NEEDS_REF_RE = /reference\s+image|upload\s+(?:an?\s+)?image|paste\s+an\s+absolute\s+path/i;

  function _addWizardMessage(text) {
    const chatStream = document.getElementById('chat-stream');
    if (!chatStream) return;
    const typing = chatStream.querySelector('.typing-indicator');
    if (typing) typing.remove();

    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant cinematographer-message';
    msgDiv.style.cssText =
      'animation:fadeIn 0.3s ease-in-out;' +
      'border-left:2px solid rgba(59,130,246,0.4);' +
      'padding-left:12px;margin:6px 0;';

    const header = document.createElement('div');
    header.style.cssText =
      'font-size:10px;color:#60a5fa;text-transform:uppercase;' +
      'letter-spacing:1px;margin-bottom:6px;';
    header.textContent = '🎬 Cinematographer';
    msgDiv.appendChild(header);

    const { prose, options } = _parseWizardOptions(text);

    if (prose) {
      const p = document.createElement('div');
      p.className = 'msg-content';
      p.innerHTML = _wcEsc(prose).replace(/\n/g, '<br>');
      msgDiv.appendChild(p);
    }

    if (options.length > 0) {
      const grid = document.createElement('div');
      grid.className = 'cinema-option-grid';
      grid.style.cssText =
        'display:flex;flex-direction:column;gap:6px;margin-top:10px;';
      const localVram = _localVramGb();
      for (const opt of options) {
        const { clean, badge, vramGb } = _splitVramBadge(opt.rawLabel);
        const exceedsLocal = (vramGb != null && localVram != null &&
                              vramGb > localVram + 0.5);
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'cinema-option-chip' +
          (exceedsLocal ? ' cinema-option-chip-low-vram' : '');
        chip.dataset.value = opt.num;
        chip.title = exceedsLocal
          ? `Exceeds local VRAM (≈${localVram.toFixed(1)} GB) — may run on a remote ComfyUI`
          : `Send: ${opt.num}`;
        chip.style.cssText =
          'display:flex;align-items:center;gap:10px;width:100%;' +
          'text-align:left;padding:8px 12px;border-radius:8px;' +
          'border:1px solid rgba(96,165,250,0.25);cursor:pointer;' +
          'background:rgba(59,130,246,0.06);color:#dbeafe;' +
          'font-family:inherit;font-size:13px;line-height:1.3;' +
          'transition:transform .12s ease, background .15s, border-color .15s;' +
          (exceedsLocal ? 'opacity:0.7;' : '');
        chip.innerHTML =
          '<span class="cinema-option-num" style="' +
            'min-width:22px;height:22px;border-radius:50%;' +
            'background:rgba(96,165,250,0.25);color:#fff;' +
            'display:inline-flex;align-items:center;justify-content:center;' +
            'font-size:11px;font-weight:700;flex:0 0 auto;">' +
            _wcEsc(opt.num) +
          '</span>' +
          '<span class="cinema-option-label" style="flex:1;">' +
            _wcEsc(clean) +
          '</span>' +
          (badge
            ? '<span class="cinema-option-badge" style="' +
                'font-size:10px;padding:2px 8px;border-radius:10px;' +
                'background:' + (exceedsLocal ? 'rgba(248,113,113,0.18)' : 'rgba(96,165,250,0.18)') + ';' +
                'color:' + (exceedsLocal ? '#fca5a5' : '#bfdbfe') + ';' +
                'flex:0 0 auto;">' + _wcEsc(badge) + '</span>'
            : '');
        chip.addEventListener('mouseenter', () => {
          chip.style.background = 'rgba(59,130,246,0.16)';
          chip.style.borderColor = 'rgba(96,165,250,0.6)';
          chip.style.transform = 'translateX(2px)';
        });
        chip.addEventListener('mouseleave', () => {
          chip.style.background = 'rgba(59,130,246,0.06)';
          chip.style.borderColor = 'rgba(96,165,250,0.25)';
          chip.style.transform = 'translateX(0)';
        });
        chip.addEventListener('click', () => {
          // Render the user's pick as a normal user bubble so chat
          // history reads naturally, then dispatch via the existing
          // _sendVideoChat path the typed-number flow uses.
          const userDiv = document.createElement('div');
          userDiv.className = 'message user';
          userDiv.style.animation = 'fadeIn 0.3s ease-in-out';
          userDiv.innerHTML =
            '<div class="msg-content">' + _wcEsc(opt.num) +
            ' <span style="opacity:0.6;font-size:12px;">(' +
            _wcEsc(clean) + ')</span></div>';
          chatStream.appendChild(userDiv);
          chatStream.scrollTop = chatStream.scrollHeight;
          // Disable every chip in this message so a double-click can't
          // double-fire the wizard.
          grid.querySelectorAll('button').forEach(b => {
            b.disabled = true;
            b.style.cursor = 'default';
            b.style.opacity = '0.5';
          });
          chip.style.opacity = '1';
          chip.style.background = 'rgba(96,165,250,0.30)';
          _sendVideoChat(opt.num);
        });
        grid.appendChild(chip);
      }
      msgDiv.appendChild(grid);
    }

    // "Reference image needed" prompts get a one-click attach button
    // that hijacks the global #upload-btn → #upload-file-input flow
    // already wired by app.js. The pending-attachment chip above the
    // composer takes over from there.
    if (_NEEDS_REF_RE.test(prose) && !options.length) {
      const actions = document.createElement('div');
      actions.style.cssText = 'margin-top:10px;display:flex;gap:8px;';
      const attach = document.createElement('button');
      attach.type = 'button';
      attach.textContent = '📎 Attach reference image';
      attach.style.cssText =
        'padding:8px 14px;border-radius:8px;cursor:pointer;' +
        'border:1px solid rgba(96,165,250,0.4);' +
        'background:rgba(96,165,250,0.18);color:#dbeafe;' +
        'font-family:inherit;font-size:13px;font-weight:600;';
      attach.addEventListener('click', () => {
        const upload = document.getElementById('upload-btn');
        if (upload) upload.click();
      });
      actions.appendChild(attach);
      msgDiv.appendChild(actions);
    }

    chatStream.appendChild(msgDiv);
    chatStream.scrollTop = chatStream.scrollHeight;
  }

  // ── Intercept the send path while Cinematographer mode is active ──
  //
  // Two interceptors, both capture-phase, both belt-and-suspenders:
  //
  // (1) Direct click on #send-btn. We attach to the button itself in
  //     capture phase so we fire BEFORE app.js's bubble-phase click
  //     handler on the same element. stopImmediatePropagation prevents
  //     app.js's handler from running and steering "1" into the main
  //     LLM chat → Spellcaster system prompt.
  //
  // (2) Enter on #chat-input. Same pattern — capture phase on the
  //     textarea, stopImmediatePropagation, then drive _sendVideoChat
  //     directly (not via a synthesized click, which has race-conditions
  //     on some browsers).
  //
  // Both paths call _submitVideoMessage() which encapsulates the "add
  // user bubble + clear input + POST to /api/video/chat" flow so there
  // is ONE code path for the Cinematographer-routed send.

  function _submitVideoMessage() {
    const text = chatInput.value.trim();
    if (!text) return;
    const chatStream = document.getElementById('chat-stream');
    if (chatStream) {
      const userDiv = document.createElement('div');
      userDiv.className = 'message user';
      userDiv.style.animation = 'fadeIn 0.3s ease-in-out';
      userDiv.innerHTML = `<div class="msg-content">${text.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</div>`;
      chatStream.appendChild(userDiv);
      chatStream.scrollTop = chatStream.scrollHeight;
    }
    chatInput.value = '';
    chatInput.style.height = 'auto';
    _sendVideoChat(text);
  }

  if (sendBtn) {
    sendBtn.addEventListener('click', (e) => {
      if (!videoChatActive) return;
      e.stopImmediatePropagation();
      e.preventDefault();
      _submitVideoMessage();
    }, true);
  }
  if (chatInput) {
    chatInput.addEventListener('keydown', (e) => {
      if (!videoChatActive) return;
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        e.stopImmediatePropagation();
        _submitVideoMessage();
      }
    }, true);
  }
})();
