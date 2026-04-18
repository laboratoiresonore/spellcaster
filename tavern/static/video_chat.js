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
      btn.style.opacity = '1';
      btn.style.background = 'rgba(59,130,246,0.2)';
      indicator.style.display = 'block';
      chatInput.placeholder = 'Describe a shot, or type a number to navigate the wizard menu...';
      // Send an initial greeting to start the wizard
      _sendVideoChat('');
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

  // ── Intercept the send button ──
  // We override by capturing the click before app.js's handler
  // using the capture phase.
  const inputArea = document.getElementById('chat-input-area');
  if (inputArea) {
    inputArea.addEventListener('click', (e) => {
      if (!videoChatActive) return;

      // Only intercept send button clicks
      const target = e.target.closest('#send-btn');
      if (!target) return;

      e.stopImmediatePropagation();
      e.preventDefault();

      const text = chatInput.value.trim();
      if (!text) return;

      // Add user message to chat
      const chatStream = document.getElementById('chat-stream');
      const userDiv = document.createElement('div');
      userDiv.className = 'message user';
      userDiv.style.animation = 'fadeIn 0.3s ease-in-out';
      userDiv.innerHTML = `<div class="msg-content">${text.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</div>`;
      chatStream.appendChild(userDiv);
      chatStream.scrollTop = chatStream.scrollHeight;

      chatInput.value = '';
      chatInput.style.height = 'auto';

      _sendVideoChat(text);
    }, true);  // capture phase — fires before app.js's bubble handler

    // Also intercept Enter key
    chatInput.addEventListener('keydown', (e) => {
      if (!videoChatActive) return;
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        e.stopImmediatePropagation();
        // Trigger the same flow as clicking send
        const fakeClick = new MouseEvent('click', { bubbles: true });
        sendBtn.dispatchEvent(fakeClick);
      }
    }, true);  // capture phase
  }
})();
