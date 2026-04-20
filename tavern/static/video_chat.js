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

  function _addWizardMessage(text) {
    const chatStream = document.getElementById('chat-stream');
    if (!chatStream) return;

    // Remove typing indicator if present
    const typing = chatStream.querySelector('.typing-indicator');
    if (typing) typing.remove();

    const msgDiv = document.createElement('div');
    msgDiv.className = 'message assistant';
    msgDiv.style.animation = 'fadeIn 0.3s ease-in-out';

    // Format numbered menus nicely (lines starting with digits)
    const formatted = text
      .replace(/\n/g, '<br>')
      .replace(/^(\d+)\.\s/gm, '<strong>$1.</strong> ');

    msgDiv.innerHTML = `
      <div class="msg-content" style="border-left:2px solid rgba(59,130,246,0.4);padding-left:12px;">
        <span style="font-size:10px;color:#60a5fa;text-transform:uppercase;letter-spacing:1px;">🎬 Cinematographer</span><br>
        ${formatted}
      </div>`;
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
