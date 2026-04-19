/*  LoRA Shootout panel — pick ONE winner per (arch, purpose_group).
 *
 *  Backend: scaffold/lora_grouping.py + tavern/server.py endpoints
 *    GET  /api/spellcaster/lora/groups
 *    POST /api/spellcaster/lora/shootout/start        → job_id
 *    GET  /api/spellcaster/lora/shootout/status?job=  → poll
 *    POST /api/spellcaster/lora/preferred             → commit winner + demote
 *
 *  UI flow:
 *    1. Entry button (#spellcaster-shootout-btn) injected top-right of Guild.
 *       Clicking opens the modal and fetches pending groups.
 *    2. Each pending (arch, purpose_group) bucket is a row with a "Run shootout"
 *       button. Click → starts a job, switches the panel into poll view.
 *    3. When status="complete", render the gallery: one tile per candidate with
 *       its image + filename + "Pick this one" button.
 *    4. On pick → POST /lora/preferred → toast confirms accepted / demoted
 *       counts → re-fetch groups → show next pending bucket (or dismiss).
 *
 *  Self-contained: no external deps. Styles live in style.css (see the
 *  `.sc-shootout-*` rules appended by this file on first run).
 */
(function () {
  'use strict';

  // ── Style injection (idempotent) ──────────────────────────────────────
  const STYLE_ID = 'sc-shootout-style';
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      #sc-shootout-btn {
        position: fixed; top: 14px; right: 20px; z-index: 999;
        background: linear-gradient(135deg, #6a1b9a, #ffd700);
        color: white; border: none; border-radius: 22px;
        padding: 8px 14px; font-size: 13px; font-weight: 600;
        cursor: pointer; box-shadow: 0 2px 10px rgba(106, 27, 154, 0.4);
        transition: transform .15s ease, box-shadow .15s ease;
      }
      #sc-shootout-btn:hover { transform: translateY(-1px);
        box-shadow: 0 4px 14px rgba(106, 27, 154, 0.55); }
      #sc-shootout-btn[data-pending="0"] { display: none; }
      #sc-shootout-btn .sc-shootout-badge {
        display: inline-block; margin-left: 6px; background: #ffd700;
        color: #4a148c; border-radius: 12px; padding: 1px 8px;
        font-weight: 700; font-size: 11px;
      }
      .sc-shootout-overlay {
        position: fixed; inset: 0; z-index: 1000;
        background: rgba(5, 3, 15, 0.85); backdrop-filter: blur(6px);
        display: flex; align-items: center; justify-content: center;
      }
      .sc-shootout-modal {
        background: #12101d; color: #e8e6f5; border-radius: 14px;
        width: 92%; max-width: 1100px; max-height: 88vh; overflow: auto;
        border: 1px solid rgba(106, 27, 154, 0.5);
        box-shadow: 0 10px 40px rgba(0,0,0,0.6);
      }
      .sc-shootout-header {
        padding: 18px 24px; border-bottom: 1px solid #2a2440;
        display: flex; align-items: center; justify-content: space-between;
      }
      .sc-shootout-header h2 { margin: 0; font-size: 18px; color: #ffd700; }
      .sc-shootout-header small { color: #a89bcc; font-size: 12px; margin-left: 8px; }
      .sc-shootout-close {
        background: none; border: 0; color: #a89bcc; font-size: 22px;
        cursor: pointer; padding: 4px 10px;
      }
      .sc-shootout-close:hover { color: #ffd700; }
      .sc-shootout-body { padding: 18px 24px; }
      .sc-shootout-empty {
        text-align: center; padding: 40px; color: #8a7eaf; font-style: italic;
      }
      .sc-shootout-group-row {
        display: flex; align-items: center; justify-content: space-between;
        padding: 14px 16px; margin: 8px 0; border-radius: 10px;
        background: #1a1730; border: 1px solid #2a2440;
      }
      .sc-shootout-group-row:hover { border-color: #6a1b9a; }
      .sc-shootout-group-info {
        display: flex; flex-direction: column; gap: 4px;
      }
      .sc-shootout-group-title {
        font-weight: 600; font-size: 15px; color: #e8e6f5;
      }
      .sc-shootout-group-arch {
        font-size: 11px; color: #a89bcc; text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .sc-shootout-group-candidates {
        font-size: 12px; color: #c4b8e3;
      }
      .sc-shootout-run-btn {
        background: linear-gradient(135deg, #6a1b9a, #9c27b0);
        color: white; border: 0; border-radius: 18px;
        padding: 8px 16px; font-size: 13px; font-weight: 600;
        cursor: pointer;
      }
      .sc-shootout-run-btn:hover { background: linear-gradient(135deg, #7b1fa2, #ba68c8); }
      .sc-shootout-run-btn:disabled { opacity: 0.5; cursor: default; }
      .sc-shootout-progress {
        display: flex; flex-direction: column; gap: 10px;
        padding: 24px; text-align: center; color: #c4b8e3;
      }
      .sc-shootout-progress .sc-bar {
        height: 6px; background: #2a2440; border-radius: 3px; overflow: hidden;
      }
      .sc-shootout-progress .sc-bar-fill {
        height: 100%; background: linear-gradient(90deg, #6a1b9a, #ffd700);
        transition: width .3s ease;
      }
      .sc-shootout-gallery {
        display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 12px; padding: 4px;
      }
      .sc-shootout-tile {
        background: #1a1730; border: 2px solid #2a2440; border-radius: 10px;
        overflow: hidden; display: flex; flex-direction: column;
      }
      .sc-shootout-tile.winner { border-color: #ffd700; box-shadow: 0 0 18px rgba(255, 215, 0, .35); }
      .sc-shootout-tile img {
        width: 100%; aspect-ratio: 1; object-fit: cover; background: #0a0815;
      }
      .sc-shootout-tile .sc-tile-meta {
        padding: 10px 12px; display: flex; flex-direction: column; gap: 6px;
      }
      .sc-shootout-tile .sc-tile-name {
        font-size: 12px; color: #e8e6f5; word-break: break-all; line-height: 1.3;
      }
      .sc-shootout-tile .sc-tile-pick {
        background: #ffd700; color: #12101d; border: 0; border-radius: 14px;
        padding: 6px 12px; font-size: 12px; font-weight: 700; cursor: pointer;
      }
      .sc-shootout-tile .sc-tile-pick:hover { background: #fff2b0; }
      .sc-shootout-tile .sc-tile-error {
        color: #ff6b6b; font-size: 12px; padding: 8px; word-break: break-word;
      }
      .sc-shootout-retry {
        display: flex; align-items: center; justify-content: center; gap: 10px;
        flex-wrap: wrap; padding: 10px 12px; margin-bottom: 14px;
        background: #1a1730; border: 1px solid #2a2440; border-radius: 10px;
      }
      .sc-shootout-retry-btn {
        background: #2a2440; color: #e8e6f5; border: 1px solid #4a3f6e;
        border-radius: 14px; padding: 6px 14px; font-size: 12px; font-weight: 600;
        cursor: pointer; white-space: nowrap;
      }
      .sc-shootout-retry-btn:hover:not(:disabled) {
        background: #3a3360; border-color: #6a1b9a;
      }
      .sc-shootout-retry-btn:disabled {
        opacity: 0.35; cursor: default;
      }
      .sc-shootout-slider-wrap {
        display: flex; align-items: center; gap: 8px; flex: 1;
        min-width: 260px; max-width: 420px;
      }
      .sc-shootout-slider-wrap input[type="range"] {
        flex: 1; accent-color: #ffd700;
      }
      #sc-retry-slider-val {
        min-width: 34px; text-align: center; font-variant-numeric: tabular-nums;
        color: #ffd700; font-weight: 600; font-size: 12px;
      }
      .sc-shootout-mega-head {
        display: flex; align-items: center; justify-content: space-between;
        padding: 10px 14px; margin-bottom: 14px; border-radius: 10px;
        background: #1a1730; border: 1px solid #2a2440;
      }
      .sc-shootout-mega-head .sc-mega-stats {
        font-size: 13px; color: #c4b8e3;
      }
      .sc-shootout-mega-head .sc-mega-stats b { color: #ffd700; }
      .sc-shootout-runall-btn {
        background: linear-gradient(135deg, #ffd700, #ff9800);
        color: #12101d; border: 0; border-radius: 18px;
        padding: 8px 16px; font-size: 13px; font-weight: 700;
        cursor: pointer;
      }
      .sc-shootout-runall-btn:hover { filter: brightness(1.1); }
      .sc-shootout-slot {
        padding: 14px 16px; margin: 10px 0; border-radius: 10px;
        background: #1a1730; border: 1px solid #2a2440;
      }
      .sc-shootout-slot.queued { opacity: 0.55; }
      .sc-shootout-slot.running { border-color: #6a1b9a; }
      .sc-shootout-slot.ready { border-color: #8a6ad1; }
      .sc-shootout-slot.picked { border-color: #ffd700; background: #1a1820; }
      .sc-shootout-slot.skipped { opacity: 0.4; }
      .sc-shootout-slot.error { border-color: #ff6b6b; }
      .sc-slot-head {
        display: flex; align-items: center; justify-content: space-between;
        gap: 10px; flex-wrap: wrap;
      }
      .sc-slot-title {
        font-size: 14px; font-weight: 600; color: #e8e6f5;
      }
      .sc-slot-arch {
        font-size: 11px; color: #a89bcc; text-transform: uppercase;
        letter-spacing: 0.5px; margin-left: 6px;
      }
      .sc-slot-badge {
        font-size: 11px; padding: 2px 8px; border-radius: 10px;
        background: #2a2440; color: #c4b8e3; white-space: nowrap;
      }
      .sc-slot-badge.running { background: #6a1b9a; color: white; }
      .sc-slot-badge.ready { background: #8a6ad1; color: white; }
      .sc-slot-badge.picked { background: #ffd700; color: #12101d; }
      .sc-slot-badge.skipped { background: #444; color: #888; }
      .sc-slot-badge.error { background: #ff6b6b; color: white; }
      .sc-slot-skip-btn {
        background: transparent; color: #8a7eaf; border: 1px solid #3a3360;
        border-radius: 12px; padding: 4px 10px; font-size: 11px;
        cursor: pointer;
      }
      .sc-slot-skip-btn:hover { color: #ffd700; border-color: #6a1b9a; }
      .sc-slot-body { margin-top: 10px; }
      .sc-slot-winner-line {
        margin-top: 8px; font-size: 13px; color: #ffd700;
      }
      .sc-shootout-toast {
        position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
        background: #12101d; color: #ffd700;
        border: 1px solid #6a1b9a; border-radius: 22px;
        padding: 10px 20px; font-size: 14px; z-index: 1100;
        box-shadow: 0 4px 18px rgba(0,0,0,0.5);
        animation: sc-toast-in 0.3s ease forwards;
      }
      @keyframes sc-toast-in {
        from { opacity: 0; transform: translate(-50%, 20px); }
        to   { opacity: 1; transform: translate(-50%, 0); }
      }
    `;
    document.head.appendChild(style);
  }

  // ── Toast helper ──────────────────────────────────────────────────────
  function toast(msg, ms) {
    const el = document.createElement('div');
    el.className = 'sc-shootout-toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), ms || 3500);
  }

  // ── Modal plumbing ────────────────────────────────────────────────────
  let overlay = null;
  let pollTimer = null;

  function close() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    if (overlay) { overlay.remove(); overlay = null; }
  }

  function mountModal(innerHTML, title) {
    if (overlay) overlay.remove();
    overlay = document.createElement('div');
    overlay.className = 'sc-shootout-overlay';
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close();
    });
    overlay.innerHTML = `
      <div class="sc-shootout-modal">
        <div class="sc-shootout-header">
          <div><h2>LoRA Shootout</h2><small>${title || ''}</small></div>
          <button class="sc-shootout-close" title="Close">✕</button>
        </div>
        <div class="sc-shootout-body" id="sc-shootout-body">${innerHTML}</div>
      </div>
    `;
    overlay.querySelector('.sc-shootout-close').addEventListener('click', close);
    document.body.appendChild(overlay);
    return overlay.querySelector('#sc-shootout-body');
  }

  // ── Data layer ────────────────────────────────────────────────────────
  async function apiFetch(path, options) {
    const resp = await fetch(path, options);
    const text = await resp.text();
    let body; try { body = JSON.parse(text); } catch { body = { raw: text }; }
    if (!resp.ok) throw new Error(body.error || `HTTP ${resp.status}`);
    return body;
  }

  async function fetchGroups() {
    return apiFetch('/api/spellcaster/lora/groups');
  }
  async function startShootout(arch, purpose_group, strength) {
    const payload = { arch, purpose_group };
    if (typeof strength === 'number' && isFinite(strength)) {
      payload.strength = strength;
    }
    return apiFetch('/api/spellcaster/lora/shootout/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }
  async function pollStatus(jobId) {
    return apiFetch(`/api/spellcaster/lora/shootout/status?job=${encodeURIComponent(jobId)}`);
  }
  async function pickWinner(arch, purpose_group, winner) {
    return apiFetch('/api/spellcaster/lora/preferred', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ arch, purpose_group, winner, demote_losers: true }),
    });
  }

  // ── Views ─────────────────────────────────────────────────────────────
  async function renderGroups() {
    const body = mountModal(`<div class="sc-shootout-empty">Loading groups…</div>`,
                            'Pending shootouts');
    try {
      const data = await fetchGroups();
      const pending = data.pending || [];
      if (!pending.length) {
        body.innerHTML =
          `<div class="sc-shootout-empty">
             🎉 No duplicate LoRAs to resolve. Run LoRA auto-setup first, or
             come back here after adding new LoRAs.
           </div>`;
        return;
      }
      const totalCandidates = pending.reduce((n, g) => n + (g.count || 0), 0);
      const header = `
        <div class="sc-shootout-mega-head">
          <div class="sc-mega-stats">
            <b>${pending.length}</b> shootout${pending.length === 1 ? '' : 's'} pending
            &nbsp;•&nbsp; <b>${totalCandidates}</b> candidate LoRAs
          </div>
          <button class="sc-shootout-runall-btn" id="sc-runall-btn"
                  title="Process every pending shootout back-to-back. You pick a winner (or skip) for each, and the next one starts automatically. ComfyUI renders one at a time.">
            ⚡ Run all shootouts
          </button>
        </div>`;
      const rows = pending.map((g) => `
        <div class="sc-shootout-group-row" data-arch="${g.arch}"
             data-group="${g.purpose_group}">
          <div class="sc-shootout-group-info">
            <div class="sc-shootout-group-title">${g.purpose_group.replace(/_/g, ' ')}</div>
            <div class="sc-shootout-group-arch">${g.arch} &nbsp;•&nbsp; ${g.count} candidates</div>
            <div class="sc-shootout-group-candidates">
              ${g.candidates.slice(0, 3).map(c => c.split(/[/\\\\]/).pop()).join(', ')}
              ${g.candidates.length > 3 ? ` +${g.candidates.length - 3} more` : ''}
            </div>
          </div>
          <button class="sc-shootout-run-btn">Run shootout</button>
        </div>
      `).join('');
      body.innerHTML = header + rows;
      body.querySelector('#sc-runall-btn')?.addEventListener('click',
        () => renderMegaPanel(pending));
      body.querySelectorAll('.sc-shootout-group-row').forEach(row => {
        row.querySelector('.sc-shootout-run-btn').addEventListener('click',
          () => runShootout(row.dataset.arch, row.dataset.group));
      });
      // Update the entry-button badge count on re-render.
      updateBadge(pending.length);
    } catch (e) {
      body.innerHTML = `<div class="sc-shootout-empty" style="color:#ff6b6b">
        Failed to load groups: ${e.message}</div>`;
    }
  }

  async function runShootout(arch, purpose_group, strength) {
    const body = mountModal('', `${arch} / ${purpose_group.replace(/_/g, ' ')}`);
    const strengthNote = (typeof strength === 'number' && isFinite(strength))
      ? ` — weight ${strength.toFixed(2)}` : '';
    body.innerHTML = `
      <div class="sc-shootout-progress">
        <div>Spawning shootout job${strengthNote}…</div>
        <div class="sc-bar"><div class="sc-bar-fill" style="width:5%"></div></div>
      </div>`;
    let jobId;
    try {
      const res = await startShootout(arch, purpose_group, strength);
      jobId = res.job_id;
    } catch (e) {
      body.innerHTML = `<div class="sc-shootout-empty" style="color:#ff6b6b">
        ${e.message}</div>`;
      return;
    }
    const poll = async () => {
      let state;
      try { state = await pollStatus(jobId); }
      catch (e) {
        body.innerHTML = `<div class="sc-shootout-empty" style="color:#ff6b6b">
          Poll failed: ${e.message}</div>`;
        return;
      }
      if (state.status === 'running') {
        const pct = state.total > 0 ? Math.round(100 * state.done / state.total) : 5;
        body.innerHTML = `
          <div class="sc-shootout-progress">
            <div>${state.done} of ${state.total} rendered${state.current ? ` — ${state.current.split(/[/\\\\]/).pop()}` : ''}</div>
            <div class="sc-bar"><div class="sc-bar-fill" style="width:${pct}%"></div></div>
          </div>`;
        pollTimer = setTimeout(poll, 1500);
        return;
      }
      if (state.status === 'error') {
        body.innerHTML = `<div class="sc-shootout-empty" style="color:#ff6b6b">
          Error: ${state.error || 'unknown'}</div>`;
        return;
      }
      renderGallery(state, arch, purpose_group);
    };
    poll();
  }

  function renderGallery(state, arch, purpose_group) {
    const body = overlay.querySelector('#sc-shootout-body');
    const samples = (state.result && state.result.samples) || [];
    if (!samples.length) {
      body.innerHTML = `<div class="sc-shootout-empty">
        No samples produced. Dispatch failed for every candidate.</div>`;
      return;
    }
    const prompt = (state.result && state.result.prompt) || '';
    const model = (state.result && state.result.model) || '';
    const currentStrength = (samples[0] && typeof samples[0].strength === 'number')
      ? samples[0].strength : 0.8;
    const stepDown = Math.max(0, Math.round((currentStrength - 0.2) * 100) / 100);
    const stepUp   = Math.min(1, Math.round((currentStrength + 0.2) * 100) / 100);
    body.innerHTML = `
      <div style="margin-bottom:14px; color:#c4b8e3; font-size:13px;">
        Pick the result that best represents how this LoRA should behave. The
        loser files stay on disk but stop being suggested.<br/>
        <small style="color:#8a7eaf">Prompt: “${prompt}” &nbsp;•&nbsp; Model: ${model}
          &nbsp;•&nbsp; weight ${currentStrength.toFixed(2)}</small>
      </div>
      <div class="sc-shootout-retry">
        <button class="sc-shootout-retry-btn" id="sc-retry-down"
                title="Re-run the shootout with LoRA weight ${stepDown.toFixed(2)} (currently ${currentStrength.toFixed(2)}). Useful when every candidate looks too strong / too stylised."
                ${stepDown >= currentStrength ? 'disabled' : ''}>↩ Retry softer</button>
        <div class="sc-shootout-slider-wrap">
          <input type="range" min="0" max="1" step="0.01"
                 value="${currentStrength.toFixed(2)}" id="sc-retry-slider"
                 title="Pick an exact LoRA weight and retry.">
          <span id="sc-retry-slider-val">${currentStrength.toFixed(2)}</span>
          <button class="sc-shootout-retry-btn" id="sc-retry-apply"
                  title="Re-run the shootout at the selected LoRA weight.">Retry at this weight</button>
        </div>
        <button class="sc-shootout-retry-btn" id="sc-retry-up"
                title="Re-run the shootout with LoRA weight ${stepUp.toFixed(2)} (currently ${currentStrength.toFixed(2)}). Useful when every candidate looks too weak / barely applied."
                ${stepUp <= currentStrength ? 'disabled' : ''}>Retry stronger ↪</button>
      </div>
      <div class="sc-shootout-gallery">
        ${samples.map((s, i) => `
          <div class="sc-shootout-tile" data-lora="${s.lora_name}">
            ${s.ok && s.image_b64
              ? `<img src="data:image/png;base64,${s.image_b64}" alt="${s.lora_name}">`
              : `<div class="sc-tile-error">${s.error || 'no image'}</div>`}
            <div class="sc-tile-meta">
              <div class="sc-tile-name">${s.lora_name.split(/[/\\\\]/).pop()}</div>
              <button class="sc-tile-pick" ${!s.ok ? 'disabled' : ''}
                      data-index="${i}">👑 Pick this one</button>
            </div>
          </div>`).join('')}
      </div>`;

    const slider = body.querySelector('#sc-retry-slider');
    const sliderVal = body.querySelector('#sc-retry-slider-val');
    if (slider && sliderVal) {
      slider.addEventListener('input', () => {
        sliderVal.textContent = parseFloat(slider.value).toFixed(2);
      });
    }
    const retryAt = (weight) => {
      if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
      runShootout(arch, purpose_group, weight);
    };
    body.querySelector('#sc-retry-down')
        ?.addEventListener('click', () => retryAt(stepDown));
    body.querySelector('#sc-retry-up')
        ?.addEventListener('click', () => retryAt(stepUp));
    body.querySelector('#sc-retry-apply')
        ?.addEventListener('click', () => retryAt(parseFloat(slider.value)));
    body.querySelectorAll('.sc-tile-pick').forEach(btn => {
      btn.addEventListener('click', async () => {
        const tile = btn.closest('.sc-shootout-tile');
        const winner = tile.dataset.lora;
        tile.classList.add('winner');
        body.querySelectorAll('.sc-tile-pick').forEach(b => b.disabled = true);
        btn.textContent = 'Committing…';
        try {
          const res = await pickWinner(arch, purpose_group, winner);
          toast(`✓ Winner: ${winner.split(/[/\\\\]/).pop()}  —  demoted ${res.demoted}`);
          setTimeout(renderGroups, 900);  // cycle to next pending bucket
        } catch (e) {
          toast(`✗ Pick failed: ${e.message}`, 5000);
          body.querySelectorAll('.sc-tile-pick').forEach(b => b.disabled = false);
          btn.textContent = '👑 Pick this one';
        }
      });
    });
  }

  // ── Entry button ──────────────────────────────────────────────────────
  function ensureEntryButton() {
    if (document.getElementById('sc-shootout-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'sc-shootout-btn';
    btn.title = 'Spellcaster LoRA Shootout — pick a winner when you have duplicates';
    btn.innerHTML = `⚔ Shootouts <span class="sc-shootout-badge">–</span>`;
    btn.addEventListener('click', renderGroups);
    document.body.appendChild(btn);
    refreshBadge();
  }

  function updateBadge(count) {
    const btn = document.getElementById('sc-shootout-btn');
    if (!btn) return;
    const badge = btn.querySelector('.sc-shootout-badge');
    if (badge) badge.textContent = String(count);
    btn.setAttribute('data-pending', String(count));
  }

  async function refreshBadge() {
    try {
      const data = await fetchGroups();
      updateBadge((data.pending || []).length);
    } catch { updateBadge(0); }
  }

  // Boot: inject the button once the page is ready; re-check every 5 min
  // so a fresh lora_autosetup + classification shows its pending buckets.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ensureEntryButton);
  } else {
    ensureEntryButton();
  }
  setInterval(refreshBadge, 5 * 60 * 1000);

  // Expose for debugging / console-driven testing.
  window.SpellcasterShootout = {
    open:    renderGroups,
    refresh: refreshBadge,
    close:   close,
  };
})();
