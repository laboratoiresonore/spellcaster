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
      /* Inline placement: sits in the chat-area slot above the text
         input, centred, so the user doesn't hunt top-right for it. */
      #sc-shootout-btn.sc-shootout-btn--inline {
        position: static;
        margin: 0 auto;
        display: inline-flex;
        align-items: center;
        gap: 6px;
      }
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
      /* ── Per-card controls (Phase 2b + 3b) ────────────────────────── */
      .sc-shootout-intro {
        padding: 10px 14px; margin-bottom: 12px; border-radius: 10px;
        background: rgba(106, 27, 154, 0.15); color: #d8c6ff;
        border: 1px solid rgba(106, 27, 154, 0.35); font-size: 13px;
        line-height: 1.45;
      }
      .sc-shootout-intro strong { color: #ffd700; }
      .sc-shootout-globals {
        background: #1a1730; border: 1px solid #2a2440; border-radius: 10px;
        padding: 10px 14px; margin-bottom: 14px; font-size: 12px;
      }
      .sc-shootout-globals summary {
        cursor: pointer; color: #c4b8e3; font-weight: 600; padding: 4px 0;
      }
      .sc-globals-row {
        display: grid; grid-template-columns: 1fr 1fr auto;
        gap: 10px; margin-top: 8px; align-items: end;
      }
      .sc-globals-row label {
        display: flex; flex-direction: column; gap: 4px;
        font-size: 11px; color: #a89bcc; text-transform: uppercase;
        letter-spacing: 0.4px;
      }
      .sc-globals-row textarea, .sc-globals-row select {
        background: #12101d; color: #e8e6f5;
        border: 1px solid #3a3360; border-radius: 6px;
        padding: 6px 8px; font-family: inherit; font-size: 12px; resize: vertical;
      }
      .sc-globals-row textarea:focus, .sc-globals-row select:focus {
        outline: none; border-color: #6a1b9a;
      }
      .sc-tile-img-wrap {
        width: 100%; aspect-ratio: 1; background: #0a0815;
        display: flex; align-items: center; justify-content: center;
      }
      .sc-tile-img-wrap img { width: 100%; height: 100%; object-fit: cover; }
      .sc-tile-controls {
        display: flex; flex-direction: column; gap: 6px; margin-top: 6px;
      }
      .sc-tile-strength {
        display: flex; align-items: center; gap: 6px;
      }
      .sc-tile-strength input[type="range"] { flex: 1; accent-color: #ffd700; }
      .sc-tile-slider-val {
        min-width: 34px; text-align: center; font-variant-numeric: tabular-nums;
        color: #ffd700; font-weight: 600; font-size: 11px;
      }
      .sc-tile-retries {
        display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px;
      }
      .sc-tile-btn {
        background: #2a2440; color: #e8e6f5; border: 1px solid #4a3f6e;
        border-radius: 10px; padding: 4px 6px; font-size: 11px; font-weight: 600;
        cursor: pointer;
      }
      .sc-tile-btn:hover:not(:disabled) {
        background: #3a3360; border-color: #6a1b9a;
      }
      .sc-tile-btn:disabled { opacity: 0.4; cursor: default; }
      .sc-tile-subject, .sc-tile-model {
        display: flex; flex-direction: column; gap: 2px; font-size: 10px;
        color: #a89bcc; text-transform: uppercase; letter-spacing: 0.4px;
      }
      .sc-tile-subject select, .sc-tile-model select {
        background: #12101d; color: #e8e6f5;
        border: 1px solid #3a3360; border-radius: 6px;
        padding: 4px 6px; font-family: inherit; font-size: 11px;
        text-transform: none; letter-spacing: 0;
      }
      .sc-tile-approve {
        margin-top: 10px; padding-top: 10px;
        border-top: 1px dashed #2a2440;
        display: flex; flex-direction: column; gap: 6px;
      }
      .sc-tile-approve-label {
        display: flex; align-items: center; gap: 6px;
        font-size: 12px; color: #ffd700; cursor: pointer; user-select: none;
      }
      .sc-tile-approve-label input[type="checkbox"] {
        accent-color: #ffd700; width: 16px; height: 16px;
      }
      .sc-tile-approve input[type="text"] {
        background: #12101d; color: #e8e6f5;
        border: 1px solid #3a3360; border-radius: 6px;
        padding: 5px 8px; font-size: 11px; font-family: inherit;
      }
      .sc-tile-approve input[type="text"]:focus {
        outline: none; border-color: #6a1b9a;
      }
      .sc-shootout-approve-bar {
        position: sticky; bottom: 0; margin-top: 14px;
        padding: 12px 14px; background: rgba(26, 23, 48, 0.95);
        border: 1px solid #2a2440; border-radius: 10px;
        display: flex; align-items: center; justify-content: space-between;
        backdrop-filter: blur(4px);
      }
      .sc-approve-count { color: #c4b8e3; font-size: 13px; }
      .sc-approve-count b { color: #ffd700; }
      .sc-shootout-approve-bar .sc-shootout-run-btn:disabled {
        opacity: 0.45; cursor: default; filter: grayscale(0.5);
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
    _megaSlots.forEach(s => {
      if (s.pollTimer) { clearTimeout(s.pollTimer); s.pollTimer = null; }
    });
    _megaSlots = [];
    _megaBusy = false;
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
  async function startShootout(arch, purpose_group, optsOrStrength) {
    const payload = { arch, purpose_group };
    // Back-compat: the mega-panel still passes a raw strength number
    // when the user hits Softer / Retry-at / Harder inside a slot.
    // Accept both shapes transparently.
    const o = (typeof optsOrStrength === 'number')
      ? { strength: optsOrStrength }
      : (optsOrStrength || {});
    if (typeof o.strength === 'number' && isFinite(o.strength)) {
      payload.strength = o.strength;
    }
    if (o.subject)  payload.subject  = o.subject;
    if (o.prompt)   payload.prompt   = o.prompt;
    if (o.negative) payload.negative = o.negative;
    if (o.model)    payload.model    = o.model;
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
  // Phase 2a — single-LoRA resample (Retry / Softer / Harder / subject swap).
  async function resampleLora(arch, purpose_group, lora_name, opts) {
    const payload = { arch, purpose_group, lora_name };
    const o = opts || {};
    if (typeof o.strength === 'number' && isFinite(o.strength)) {
      payload.strength = o.strength;
    }
    if (o.subject)  payload.subject  = o.subject;
    if (o.prompt)   payload.prompt   = o.prompt;
    if (o.negative) payload.negative = o.negative;
    if (o.model)    payload.model    = o.model;
    if (typeof o.seed === 'number') payload.seed = o.seed;
    return apiFetch('/api/spellcaster/lora/shootout/sample', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  }
  // Phase 3a — approve many LoRAs at once, each with its own keywords.
  async function approveLoras(approvals) {
    return apiFetch('/api/spellcaster/lora/approve', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approvals }),
    });
  }
  async function fetchSubjects() {
    try { return (await apiFetch('/api/spellcaster/lora/subjects')).subjects || []; }
    catch { return []; }
  }
  async function fetchModelsForArch(arch) {
    // /api/available_models returns {models: [{name, arch, ...}]}.
    try {
      const res = await apiFetch('/api/available_models');
      return (res.models || []).filter(m => m.arch === arch);
    } catch { return []; }
  }
  // Cache subjects once — they're static for the session.
  let _subjectsCache = null;
  async function getSubjects() {
    if (_subjectsCache) return _subjectsCache;
    _subjectsCache = await fetchSubjects();
    return _subjectsCache;
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

  async function runShootout(arch, purpose_group, opts) {
    opts = opts || {};
    const body = mountModal('', `${arch} / ${purpose_group.replace(/_/g, ' ')}`);
    const strengthNote =
      (typeof opts.strength === 'number' && isFinite(opts.strength))
        ? ` — weight ${opts.strength.toFixed(2)}` : '';
    body.innerHTML = `
      <div class="sc-shootout-progress">
        <div>Spawning shootout job${strengthNote}…</div>
        <div class="sc-bar"><div class="sc-bar-fill" style="width:5%"></div></div>
      </div>`;
    let jobId;
    try {
      const res = await startShootout(arch, purpose_group, opts);
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

  // Build a per-card tile element. Holds its own slider, retry/softer/harder
  // buttons, subject dropdown, approve checkbox, keyword input, description
  // input. The slider + subject + model picker in the tile drive the
  // per-LoRA resample endpoint; the top "Global controls" box drives the
  // batch shootout restart button (which re-renders every card at once).
  async function _buildTile(sample, arch, purpose_group, subjects, archModels) {
    const currentStrength = (typeof sample.strength === 'number') ? sample.strength : 0.7;
    const effSubject = sample.subject || '';
    const tile = document.createElement('div');
    tile.className = 'sc-shootout-tile';
    tile.dataset.lora = sample.lora_name;
    const displayName = sample.lora_name.split(/[/\\\\]/).pop();
    const subjectOpts = subjects.map(s =>
      `<option value="${s.key}"${effSubject === s.key ? ' selected' : ''}>${s.label}</option>`
    ).join('');
    const modelOpts = ['<option value="">(auto — best match)</option>']
      .concat(archModels.map(m =>
        `<option value="${m.name}">${m.name}</option>`
      )).join('');
    tile.innerHTML = `
      <div class="sc-tile-img-wrap">
        ${sample.ok && sample.image_b64
          ? `<img src="data:image/png;base64,${sample.image_b64}" alt="${displayName}">`
          : `<div class="sc-tile-error">${sample.error || 'no image'}</div>`}
      </div>
      <div class="sc-tile-meta">
        <div class="sc-tile-name" title="${sample.lora_name}">${displayName}</div>
        <div class="sc-tile-controls">
          <div class="sc-tile-strength">
            <input type="range" min="0" max="1.5" step="0.05"
                   value="${currentStrength.toFixed(2)}" class="sc-tile-slider">
            <span class="sc-tile-slider-val">${currentStrength.toFixed(2)}</span>
          </div>
          <div class="sc-tile-retries">
            <button class="sc-tile-btn sc-tile-softer" title="Retry at weight × 0.6 (stacks)">Softer</button>
            <button class="sc-tile-btn sc-tile-retry"  title="Retry at the slider's weight">Retry</button>
            <button class="sc-tile-btn sc-tile-harder" title="Retry at weight × 1.3 (stacks)">Harder</button>
          </div>
          <div class="sc-tile-subject">
            <label>Subject</label>
            <select class="sc-tile-subject-sel">${subjectOpts}</select>
          </div>
          <div class="sc-tile-model">
            <label>Model</label>
            <select class="sc-tile-model-sel">${modelOpts}</select>
          </div>
        </div>
        <div class="sc-tile-approve">
          <label class="sc-tile-approve-label">
            <input type="checkbox" class="sc-tile-approve-cb">
            <span>Approve this LoRA</span>
          </label>
          <input type="text" class="sc-tile-keywords"
                 placeholder="Keywords that should auto-trigger this LoRA (comma-separated)"
                 title="When one of these keywords appears in a wizard prompt, the Guild will auto-suggest this LoRA.">
          <input type="text" class="sc-tile-description"
                 placeholder="Short description (optional)">
        </div>
      </div>`;

    // Wire live slider → label
    const slider = tile.querySelector('.sc-tile-slider');
    const sliderVal = tile.querySelector('.sc-tile-slider-val');
    slider.addEventListener('input', () => {
      sliderVal.textContent = parseFloat(slider.value).toFixed(2);
    });

    // Per-card resample flow — swap in a pending image + call the sample
    // endpoint. On success replace the image; on failure show the error
    // but keep the card's controls so the user can tweak + try again.
    const resampleAt = async (strength) => {
      const subject = tile.querySelector('.sc-tile-subject-sel').value;
      const model = tile.querySelector('.sc-tile-model-sel').value;
      const wrap = tile.querySelector('.sc-tile-img-wrap');
      wrap.innerHTML = `<div class="sc-tile-error" style="color:#8a7eaf">Rendering…</div>`;
      tile.querySelectorAll('.sc-tile-btn').forEach(b => b.disabled = true);
      try {
        const body = overlay.querySelector('#sc-shootout-body');
        const globalPrompt = body.querySelector('#sc-global-prompt')?.value || '';
        const globalNeg = body.querySelector('#sc-global-negative')?.value || '';
        const res = await resampleLora(arch, purpose_group, sample.lora_name, {
          strength: typeof strength === 'number' ? strength : parseFloat(slider.value),
          subject: subject || undefined,
          model: model || undefined,
          prompt: globalPrompt || undefined,
          negative: globalNeg || undefined,
        });
        // Update tile state from server response
        sample.strength = res.strength; sample.image_b64 = res.image_b64;
        sample.ok = res.ok; sample.error = res.error || '';
        sample.subject = res.subject || subject;
        // HTML-escape for attacker-reachable strings landing in innerHTML.
        const _escH = s => String(s == null ? '' : s)
            .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
            .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
        if (res.ok && res.image_b64) {
          // image_b64 is base64 (no HTML-special chars by spec) but
          // displayName is user-facing LoRA name — always escape.
          wrap.innerHTML = `<img src="data:image/png;base64,${res.image_b64}" alt="${_escH(displayName)}">`;
        } else {
          wrap.innerHTML = `<div class="sc-tile-error">${_escH(res.error || 'no image')}</div>`;
        }
        slider.value = res.strength.toFixed(2);
        sliderVal.textContent = res.strength.toFixed(2);
      } catch (e) {
        const _escH = s => String(s == null ? '' : s)
            .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
            .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
        wrap.innerHTML = `<div class="sc-tile-error">resample failed: ${_escH(e.message)}</div>`;
      } finally {
        tile.querySelectorAll('.sc-tile-btn').forEach(b => b.disabled = false);
      }
    };
    tile.querySelector('.sc-tile-retry').addEventListener('click',
      () => resampleAt(parseFloat(slider.value)));
    tile.querySelector('.sc-tile-softer').addEventListener('click',
      () => resampleAt(Math.max(0, parseFloat(slider.value) * 0.6)));
    tile.querySelector('.sc-tile-harder').addEventListener('click',
      () => resampleAt(Math.min(1.5, parseFloat(slider.value) * 1.3)));
    // Subject swap or model swap → resample immediately at current weight.
    tile.querySelector('.sc-tile-subject-sel').addEventListener('change',
      () => resampleAt(parseFloat(slider.value)));
    tile.querySelector('.sc-tile-model-sel').addEventListener('change',
      () => resampleAt(parseFloat(slider.value)));
    return tile;
  }

  async function renderGallery(state, arch, purpose_group) {
    const body = overlay.querySelector('#sc-shootout-body');
    const samples = (state.result && state.result.samples) || [];
    if (!samples.length) {
      body.innerHTML = `<div class="sc-shootout-empty">
        No samples produced. Dispatch failed for every candidate.</div>`;
      return;
    }
    const prompt = (state.result && state.result.prompt) || '';
    const negative = (state.result && state.result.negative) || '';
    const model = (state.result && state.result.model) || '';
    // Fetch subjects + model list in parallel — small queries, cached.
    const [subjects, archModels] = await Promise.all([
      getSubjects(), fetchModelsForArch(arch),
    ]);
    const subjectGlobalOpts = subjects.map(s =>
      `<option value="${s.key}">${s.label}</option>`
    ).join('');
    const modelGlobalOpts = ['<option value="">(auto)</option>']
      .concat(archModels.map(m =>
        `<option value="${m.name}"${m.name === model ? ' selected' : ''}>${m.name}</option>`
      )).join('');
    body.innerHTML = `
      <div class="sc-shootout-intro">
        <strong>Approve every LoRA you want the Guild to use.</strong>
        Each card has its own slider, retry buttons, subject, and model
        picker. Approved LoRAs stay usable — the Wizard Guild auto-
        suggests them when one of your keywords appears in a prompt.
      </div>
      <details class="sc-shootout-globals" open>
        <summary>Global controls (apply to every new card + batch re-run)</summary>
        <div class="sc-globals-row">
          <label>Prompt<textarea id="sc-global-prompt" rows="2"
                                  placeholder="Leave blank to use the subject template">${escapeHTML(prompt)}</textarea></label>
          <label>Negative<textarea id="sc-global-negative" rows="2"
                                    placeholder="Leave blank to use the subject template">${escapeHTML(negative)}</textarea></label>
        </div>
        <div class="sc-globals-row">
          <label>Batch subject
            <select id="sc-global-subject"><option value="">(keep per-card)</option>${subjectGlobalOpts}</select>
          </label>
          <label>Model
            <select id="sc-global-model">${modelGlobalOpts}</select>
          </label>
          <button id="sc-global-rerun" class="sc-shootout-retry-btn"
                  title="Re-run every card with the global controls above (slow — one render per LoRA).">Re-run all</button>
        </div>
      </details>
      <div class="sc-shootout-gallery" id="sc-gallery"></div>
      <div class="sc-shootout-approve-bar">
        <div class="sc-approve-count"><b id="sc-approve-count">0</b> selected</div>
        <button class="sc-shootout-run-btn" id="sc-approve-submit" disabled>
          Approve selected LoRAs
        </button>
      </div>`;

    const gallery = body.querySelector('#sc-gallery');
    for (const s of samples) {
      gallery.appendChild(await _buildTile(s, arch, purpose_group,
                                            subjects, archModels));
    }
    // Approve-count wiring
    const countEl = body.querySelector('#sc-approve-count');
    const submitBtn = body.querySelector('#sc-approve-submit');
    const updateApproveCount = () => {
      const n = body.querySelectorAll('.sc-tile-approve-cb:checked').length;
      countEl.textContent = String(n);
      submitBtn.disabled = n === 0;
    };
    body.querySelectorAll('.sc-tile-approve-cb').forEach(cb =>
      cb.addEventListener('change', updateApproveCount));
    // Global re-run — fires the batch endpoint with current global overrides.
    body.querySelector('#sc-global-rerun').addEventListener('click', () => {
      const opts = {
        prompt:   body.querySelector('#sc-global-prompt').value || undefined,
        negative: body.querySelector('#sc-global-negative').value || undefined,
        subject:  body.querySelector('#sc-global-subject').value || undefined,
        model:    body.querySelector('#sc-global-model').value || undefined,
      };
      runShootout(arch, purpose_group, opts);
    });
    // Approve submit — send all checked tiles with their per-card keywords.
    submitBtn.addEventListener('click', async () => {
      const approvals = [];
      body.querySelectorAll('.sc-shootout-tile').forEach(tile => {
        if (!tile.querySelector('.sc-tile-approve-cb').checked) return;
        const kws = tile.querySelector('.sc-tile-keywords').value.trim();
        const desc = tile.querySelector('.sc-tile-description').value.trim();
        approvals.push({
          name: tile.dataset.lora,
          keywords: kws ? kws.split(',').map(s => s.trim()).filter(Boolean) : [],
          description: desc,
          strength: parseFloat(tile.querySelector('.sc-tile-slider').value),
          subject: tile.querySelector('.sc-tile-subject-sel').value || undefined,
        });
      });
      if (!approvals.length) return;
      submitBtn.disabled = true;
      submitBtn.textContent = 'Saving…';
      try {
        const res = await approveLoras(approvals);
        toast(`✓ Approved ${res.accepted.length} LoRAs`);
        setTimeout(renderGroups, 900);
      } catch (e) {
        toast(`✗ Approve failed: ${e.message}`, 5000);
        submitBtn.disabled = false;
        submitBtn.textContent = 'Approve selected LoRAs';
      }
    });
  }

  function escapeHTML(s) {
    return String(s || '').replace(/[&<>"']/g, c =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // ── Run-all mega panel ────────────────────────────────────────────────
  //
  // Sequential processor: one slot per pending group. ComfyUI only renders
  // one shootout at a time so we respect that — the first QUEUED slot
  // becomes RUNNING; once it's READY the user picks or skips, then the
  // next one advances. User can pick/skip out of order via per-slot
  // controls; the controller just always advances the first remaining
  // QUEUED slot whenever ComfyUI is free.
  let _megaSlots = [];          // [{arch, purpose_group, count, status, el, jobId, result, pollTimer}]
  let _megaBusy = false;

  function _slotStatus(slot, status, badgeText) {
    slot.status = status;
    slot.el.className = `sc-shootout-slot ${status}`;
    const badge = slot.el.querySelector('.sc-slot-badge');
    if (badge) {
      badge.className = `sc-slot-badge ${status}`;
      badge.textContent = badgeText || status;
    }
  }

  function _updateMegaStats() {
    const head = overlay && overlay.querySelector('#sc-mega-stats');
    if (!head) return;
    const counts = { queued: 0, running: 0, ready: 0, picked: 0, skipped: 0, error: 0 };
    _megaSlots.forEach(s => counts[s.status] = (counts[s.status] || 0) + 1);
    head.innerHTML = `<b>${counts.picked}</b> done
      &nbsp;•&nbsp; <b>${counts.running}</b> running
      &nbsp;•&nbsp; <b>${counts.queued}</b> queued
      &nbsp;•&nbsp; <b>${counts.ready}</b> awaiting pick
      ${counts.skipped ? `&nbsp;•&nbsp; ${counts.skipped} skipped` : ''}
      ${counts.error ? `&nbsp;•&nbsp; <span style="color:#ff6b6b">${counts.error} failed</span>` : ''}`;
  }

  async function _renderSlotGallery(slot) {
    const state = slot.jobState;
    const samples = (state.result && state.result.samples) || [];
    const body = slot.el.querySelector('.sc-slot-body');
    if (!samples.length) {
      body.innerHTML = `<div class="sc-tile-error">No samples produced.</div>`;
      _slotStatus(slot, 'error', 'no samples');
      _updateMegaStats();
      _advanceMegaQueue();
      return;
    }
    const prompt = (state.result && state.result.prompt) || '';
    const negative = (state.result && state.result.negative) || '';
    const model  = (state.result && state.result.model) || '';

    // R137: every slot now gets the full approve-many UI that the
    // single-group view uses — per-tile strength slider, retry
    // buttons, subject dropdown, model picker, approve checkbox,
    // keyword input, description input. No more "Pick ONE winner"
    // only; for "other" with 29 SDXL LoRAs the user approves every
    // one they want and attaches keywords. For named categories
    // (hand_fix / feet_fix / ...) the "Pick winner" action is still
    // one click away via the per-tile crown button.
    const [subjects, archModels] = await Promise.all([
      getSubjects(), fetchModelsForArch(slot.arch),
    ]);
    const subjectGlobalOpts = subjects.map(s =>
      `<option value="${s.key}">${s.label}</option>`
    ).join('');
    const modelGlobalOpts = ['<option value="">(auto)</option>']
      .concat(archModels.map(m =>
        `<option value="${m.name}"${m.name === model ? ' selected' : ''}>${m.name}</option>`
      )).join('');
    const isOtherBucket = slot.purpose_group === 'other';
    body.innerHTML = `
      <details class="sc-shootout-globals" open>
        <summary>Test prompt &amp; controls for this group</summary>
        <div class="sc-globals-row">
          <label>Prompt<textarea class="sc-slot-prompt" rows="2"
                                  placeholder="Leave blank to reuse the subject template">${escapeHTML(prompt)}</textarea></label>
          <label>Negative<textarea class="sc-slot-negative" rows="2"
                                    placeholder="Leave blank to reuse the subject template">${escapeHTML(negative)}</textarea></label>
        </div>
        <div class="sc-globals-row">
          <label>Batch subject
            <select class="sc-slot-subject"><option value="">(keep per-card)</option>${subjectGlobalOpts}</select>
          </label>
          <label>Model
            <select class="sc-slot-model">${modelGlobalOpts}</select>
          </label>
          <button class="sc-shootout-retry-btn sc-slot-rerun"
                  title="Re-run every card below with the prompt/negative/subject/model above (one render per LoRA, slow).">Re-run all</button>
        </div>
        <div class="sc-globals-row" style="grid-template-columns: 1fr auto;">
          <label>Batch keyword
            <input type="text" class="sc-slot-batch-keyword"
                   placeholder="Typed in Guild prompts → auto-suggest every LoRA approved in this group"
                   style="background:#12101d;color:#e8e6f5;border:1px solid #3a3360;border-radius:6px;padding:6px 8px;font-family:inherit;font-size:12px;">
          </label>
          <button class="sc-shootout-retry-btn sc-slot-apply-keyword"
                  title="Append this keyword to every approved card's keyword field below.">Apply to approved</button>
        </div>
      </details>
      <div class="sc-shootout-gallery sc-slot-gallery"></div>
      <div class="sc-shootout-approve-bar">
        <div class="sc-approve-count">
          <b class="sc-slot-approve-count">0</b> approved in this group
          ${isOtherBucket ? '' : '&nbsp;•&nbsp; <span style="color:#8a7eaf;">(tip: a named category usually only needs one winner)</span>'}
        </div>
        <div style="display:flex;gap:8px;">
          <button class="sc-shootout-retry-btn sc-slot-approve-all"
                  title="Tick every card's Approve checkbox (useful for 'other' buckets).">Approve all</button>
          <button class="sc-shootout-run-btn sc-slot-approve-submit" disabled>
            Approve selected
          </button>
        </div>
      </div>`;

    const gallery = body.querySelector('.sc-slot-gallery');
    for (const s of samples) {
      gallery.appendChild(await _buildTile(s, slot.arch, slot.purpose_group,
                                            subjects, archModels));
    }

    // Approve-count wiring
    const countEl = body.querySelector('.sc-slot-approve-count');
    const submitBtn = body.querySelector('.sc-slot-approve-submit');
    const updateApproveCount = () => {
      const n = body.querySelectorAll('.sc-tile-approve-cb:checked').length;
      countEl.textContent = String(n);
      submitBtn.disabled = n === 0;
    };
    body.querySelectorAll('.sc-tile-approve-cb').forEach(cb =>
      cb.addEventListener('change', updateApproveCount));

    // "Approve all" quick action
    body.querySelector('.sc-slot-approve-all')?.addEventListener('click', () => {
      body.querySelectorAll('.sc-tile-approve-cb').forEach(cb => {
        cb.checked = true;
      });
      updateApproveCount();
    });

    // "Apply batch keyword to every approved card's keyword field"
    body.querySelector('.sc-slot-apply-keyword')?.addEventListener('click', () => {
      const kw = body.querySelector('.sc-slot-batch-keyword').value.trim();
      if (!kw) { toast('Type a keyword first.', 2500); return; }
      let n = 0;
      body.querySelectorAll('.sc-shootout-tile').forEach(tile => {
        const cb = tile.querySelector('.sc-tile-approve-cb');
        // Apply to approved tiles (or every tile if nothing's approved
        // yet — user intent is "tag these with this keyword").
        const approvedAny = !!body.querySelector('.sc-tile-approve-cb:checked');
        if (approvedAny && !cb.checked) return;
        const kwInput = tile.querySelector('.sc-tile-keywords');
        const existing = kwInput.value.trim();
        const tokens = existing ? existing.split(',').map(t => t.trim()).filter(Boolean) : [];
        if (!tokens.includes(kw)) {
          tokens.push(kw);
          kwInput.value = tokens.join(', ');
          n += 1;
        }
      });
      toast(`✓ Added "${kw}" to ${n} LoRA${n === 1 ? '' : 's'}`);
    });

    // Re-run this slot with the new globals
    body.querySelector('.sc-slot-rerun')?.addEventListener('click', () => {
      if (slot.pollTimer) { clearTimeout(slot.pollTimer); slot.pollTimer = null; }
      _runMegaSlot(slot, undefined, {
        prompt:   body.querySelector('.sc-slot-prompt').value || undefined,
        negative: body.querySelector('.sc-slot-negative').value || undefined,
        subject:  body.querySelector('.sc-slot-subject').value || undefined,
        model:    body.querySelector('.sc-slot-model').value || undefined,
      });
    });

    // Approve submit — send every checked tile with its own keywords.
    submitBtn.addEventListener('click', async () => {
      const approvals = [];
      body.querySelectorAll('.sc-shootout-tile').forEach(tile => {
        if (!tile.querySelector('.sc-tile-approve-cb').checked) return;
        const kws = tile.querySelector('.sc-tile-keywords').value.trim();
        const desc = tile.querySelector('.sc-tile-description').value.trim();
        approvals.push({
          name: tile.dataset.lora,
          keywords: kws ? kws.split(',').map(s => s.trim()).filter(Boolean) : [],
          description: desc,
          strength: parseFloat(tile.querySelector('.sc-tile-slider').value),
          subject: tile.querySelector('.sc-tile-subject-sel').value || undefined,
        });
      });
      if (!approvals.length) return;
      submitBtn.disabled = true;
      submitBtn.textContent = 'Saving…';
      try {
        const res = await approveLoras(approvals);
        _slotStatus(slot, 'picked', `✓ ${res.accepted.length} approved`);
        _updateMegaStats();
        body.querySelectorAll('.sc-tile-approve-cb').forEach(cb =>
          cb.disabled = true);
        submitBtn.textContent = `✓ Saved ${res.accepted.length}`;
        refreshBadge();
      } catch (e) {
        toast(`✗ Approve failed: ${e.message}`, 5000);
        submitBtn.disabled = false;
        submitBtn.textContent = 'Approve selected';
      }
    });

    _slotStatus(slot, 'ready', 'review + approve');
    _updateMegaStats();
    // Free ComfyUI so the next queued slot can start in parallel with
    // the user's review.
    _advanceMegaQueue();
  }

  async function _runMegaSlot(slot, strength, overrides) {
    if (slot.pollTimer) { clearTimeout(slot.pollTimer); slot.pollTimer = null; }
    _slotStatus(slot, 'running', 'starting…');
    _updateMegaStats();
    const body = slot.el.querySelector('.sc-slot-body');
    body.innerHTML = `
      <div class="sc-shootout-progress">
        <div>Spawning…</div>
        <div class="sc-bar"><div class="sc-bar-fill" style="width:5%"></div></div>
      </div>`;
    // Merge optional per-slot overrides with top-level mega-panel
    // overrides (prompt/negative/subject/model set in the panel
    // header apply to every slot unless the per-slot panel overrides
    // them).
    const startOpts = Object.assign({},
      (window._MEGA_OVERRIDES || {}),
      overrides || {});
    if (typeof strength === 'number' && isFinite(strength)) {
      startOpts.strength = strength;
    }
    try {
      const res = await startShootout(slot.arch, slot.purpose_group, startOpts);
      slot.jobId = res.job_id;
    } catch (e) {
      body.innerHTML = `<div class="sc-tile-error">${e.message}</div>`;
      _slotStatus(slot, 'error', 'failed');
      _updateMegaStats();
      _megaBusy = false;
      _advanceMegaQueue();
      return;
    }
    const poll = async () => {
      let state;
      try { state = await pollStatus(slot.jobId); }
      catch (e) {
        body.innerHTML = `<div class="sc-tile-error">poll failed: ${e.message}</div>`;
        _slotStatus(slot, 'error', 'poll err');
        _updateMegaStats();
        _megaBusy = false;
        _advanceMegaQueue();
        return;
      }
      if (state.status === 'running') {
        const pct = state.total > 0 ? Math.round(100 * state.done / state.total) : 5;
        const tail = state.current ? ` — ${state.current.split(/[/\\\\]/).pop()}` : '';
        body.innerHTML = `
          <div class="sc-shootout-progress">
            <div>${state.done} of ${state.total}${tail}</div>
            <div class="sc-bar"><div class="sc-bar-fill" style="width:${pct}%"></div></div>
          </div>`;
        _slotStatus(slot, 'running', `${state.done}/${state.total}`);
        slot.pollTimer = setTimeout(poll, 1500);
        return;
      }
      if (state.status === 'error') {
        body.innerHTML = `<div class="sc-tile-error">${state.error || 'unknown'}</div>`;
        _slotStatus(slot, 'error', 'error');
        _updateMegaStats();
        _megaBusy = false;
        _advanceMegaQueue();
        return;
      }
      slot.jobState = state;
      _megaBusy = false;
      _renderSlotGallery(slot);
    };
    poll();
  }

  function _advanceMegaQueue() {
    if (_megaBusy) return;
    const next = _megaSlots.find(s => s.status === 'queued');
    if (!next) return;
    _megaBusy = true;
    _runMegaSlot(next);
  }

  async function renderMegaPanel(preloadedPending) {
    const body = mountModal(
      `<div class="sc-shootout-empty">Loading…</div>`,
      'Run all shootouts');
    let pending = preloadedPending;
    if (!pending) {
      try { pending = (await fetchGroups()).pending || []; }
      catch (e) {
        body.innerHTML = `<div class="sc-shootout-empty" style="color:#ff6b6b">
          ${e.message}</div>`;
        return;
      }
    }
    if (!pending.length) {
      body.innerHTML = `<div class="sc-shootout-empty">
        🎉 All LoRAs already calibrated.</div>`;
      return;
    }
    _megaSlots = pending.map((g) => ({
      arch: g.arch, purpose_group: g.purpose_group,
      count: g.count, candidates: g.candidates || [],
      status: 'queued', el: null, jobId: null, jobState: null,
      pollTimer: null,
    }));
    _megaBusy = false;
    window._MEGA_OVERRIDES = {};
    // Collect ALL archs present so the mega-panel can pre-fetch their
    // subject list + model list without waiting for each slot.
    const subjects = await getSubjects();
    const subjectGlobalOpts = subjects.map(s =>
      `<option value="${s.key}">${s.label}</option>`
    ).join('');
    body.innerHTML = `
      <div class="sc-shootout-mega-head">
        <div class="sc-mega-stats" id="sc-mega-stats"></div>
      </div>
      <details class="sc-shootout-globals" open style="margin-bottom:14px;">
        <summary>Global test overrides (apply to every group below)</summary>
        <div class="sc-globals-row">
          <label>Prompt<textarea id="sc-mega-prompt" rows="2"
                                  placeholder="Override the default subject template for every slot"></textarea></label>
          <label>Negative<textarea id="sc-mega-negative" rows="2"
                                    placeholder="Override the default negative"></textarea></label>
        </div>
        <div class="sc-globals-row">
          <label>Batch subject
            <select id="sc-mega-subject"><option value="">(keep per-group)</option>${subjectGlobalOpts}</select>
          </label>
          <label>Batch keyword
            <input type="text" id="sc-mega-batch-keyword"
                   placeholder="Applied to every approved LoRA after 'Apply keyword'"
                   style="background:#12101d;color:#e8e6f5;border:1px solid #3a3360;border-radius:6px;padding:6px 8px;font-family:inherit;font-size:12px;">
          </label>
          <button id="sc-mega-apply-keyword" class="sc-shootout-retry-btn"
                  title="Append the batch keyword to every approved card across every ready/picked slot. Useful for 'this is my SDXL realism toolkit' style tagging.">Apply keyword</button>
        </div>
        <div style="margin-top:8px; font-size:11px; color:#8a7eaf;">
          Values above are used when a slot starts or is re-run. Each
          slot has its own per-tile strength slider, subject picker,
          approve checkbox, keyword list, and description.
        </div>
      </details>
      <div id="sc-mega-slots"></div>`;

    // Top-level Apply keyword — fills empty keyword fields across
    // EVERY ready slot so the user can tag their whole "SDXL realism"
    // batch in one shot.
    body.querySelector('#sc-mega-apply-keyword').addEventListener('click', () => {
      const kw = body.querySelector('#sc-mega-batch-keyword').value.trim();
      if (!kw) { toast('Type a keyword first.', 2500); return; }
      let n = 0;
      body.querySelectorAll('.sc-slot-body .sc-shootout-tile').forEach(tile => {
        const cb = tile.querySelector('.sc-tile-approve-cb');
        if (!cb || !cb.checked) return;
        const kwInput = tile.querySelector('.sc-tile-keywords');
        if (!kwInput) return;
        const existing = kwInput.value.trim();
        const tokens = existing ? existing.split(',').map(t => t.trim()).filter(Boolean) : [];
        if (!tokens.includes(kw)) {
          tokens.push(kw);
          kwInput.value = tokens.join(', ');
          n += 1;
        }
      });
      toast(`✓ Tagged ${n} approved LoRA${n === 1 ? '' : 's'} with "${kw}"`);
    });

    // Plumb prompt/negative/subject into _runMegaSlot via a module
    // global — _runMegaSlot merges them into every startShootout call.
    const updateOverrides = () => {
      window._MEGA_OVERRIDES = {
        prompt:   body.querySelector('#sc-mega-prompt').value || undefined,
        negative: body.querySelector('#sc-mega-negative').value || undefined,
        subject:  body.querySelector('#sc-mega-subject').value || undefined,
      };
    };
    body.querySelector('#sc-mega-prompt').addEventListener('input', updateOverrides);
    body.querySelector('#sc-mega-negative').addEventListener('input', updateOverrides);
    body.querySelector('#sc-mega-subject').addEventListener('change', updateOverrides);
    const slotsEl = body.querySelector('#sc-mega-slots');
    _megaSlots.forEach((slot) => {
      const el = document.createElement('div');
      el.className = 'sc-shootout-slot queued';
      el.innerHTML = `
        <div class="sc-slot-head">
          <div>
            <span class="sc-slot-title">${slot.purpose_group.replace(/_/g, ' ')}</span>
            <span class="sc-slot-arch">${slot.arch} &nbsp;•&nbsp; ${slot.count} candidates</span>
          </div>
          <div style="display:flex;gap:8px;align-items:center;">
            <span class="sc-slot-badge queued">queued</span>
            <button class="sc-slot-skip-btn" title="Skip this group — leave its LoRAs untouched.">Skip</button>
          </div>
        </div>
        <div class="sc-slot-body"></div>`;
      slotsEl.appendChild(el);
      slot.el = el;
      el.querySelector('.sc-slot-skip-btn').addEventListener('click', () => {
        const wasRunning = slot.status === 'running';
        if (slot.pollTimer) { clearTimeout(slot.pollTimer); slot.pollTimer = null; }
        _slotStatus(slot, 'skipped', 'skipped');
        el.querySelector('.sc-slot-body').innerHTML = '';
        _updateMegaStats();
        if (wasRunning) _megaBusy = false;
        _advanceMegaQueue();
      });
    });
    _updateMegaStats();
    _advanceMegaQueue();
  }

  // ── Entry button ──────────────────────────────────────────────────────
  // The button lives in #chat-shootout-slot (above the chat input,
  // centred in the chat area) when that slot exists, so the user can
  // reach shootouts without hunting in the top-right corner. If the
  // slot isn't in the DOM yet (setup wizard pages, etc.) we fall back
  // to a floating top-right button so the UX stays usable.
  function ensureEntryButton() {
    if (document.getElementById('sc-shootout-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'sc-shootout-btn';
    btn.title = 'Spellcaster LoRA Shootout — pick a winner when you have duplicates';
    btn.innerHTML = `⚔ Shootouts <span class="sc-shootout-badge">–</span>`;
    btn.addEventListener('click', renderGroups);
    const slot = document.getElementById('chat-shootout-slot');
    if (slot) {
      btn.classList.add('sc-shootout-btn--inline');
      slot.appendChild(btn);
    } else {
      document.body.appendChild(btn);
    }
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
