/*  LoRA Auto-Calibrate — one-click recipe confirmation.
 *
 *  Backend: scaffold/lora_grouping.py::start_calibration_job + Civitai/
 *  safetensors knowledge in spellcaster_core/lora_knowledge.py.
 *
 *  Flow:
 *    1. Entry button (#sc-cal-btn) sits next to the Shootouts button.
 *       Count is the # of unconfirmed LoRAs from the registry.
 *    2. Click → modal opens and the user hits "Auto-calibrate N LoRAs".
 *    3. Server renders ONE sample per unconfirmed LoRA using the LoRA's
 *       own recipe (Civitai weight + triggers, safetensors triggers,
 *       sidecar .civitai.info, shipped defaults, heuristic fill-in).
 *    4. Cards stream in as the worker finishes each. Each card has a
 *       ✓ Confirm button — click writes the recipe to the SFW or NSFW
 *       calibration store and flips the registry flag so the LoRA
 *       disappears from "unconfirmed" the next time the panel opens.
 *    5. A "Confirm all visible" sweep accepts every rendered sample.
 *       "Customize" on any card hands off to the existing Shootouts
 *       UI so the user can tweak the recipe manually.
 *
 *  Endpoints used:
 *    GET  /api/spellcaster/lora/calibrate/summary
 *    POST /api/spellcaster/lora/calibrate/auto/start
 *    GET  /api/spellcaster/lora/calibrate/auto/status?job=
 *    POST /api/spellcaster/lora/calibrate/confirm
 *    GET  /api/spellcaster/lora/knowledge?name=
 */
(function () {
  'use strict';

  const STYLE_ID = 'sc-cal-style';
  if (!document.getElementById(STYLE_ID)) {
    const s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = `
      #sc-cal-btn {
        /* Fallback layout only — normally the button lives inline in
           #chat-shootout-slot (between Shootouts and the Turbo preset
           cycler). We put the fixed-position fallback BELOW the
           shootout button (top:52px) and at right:20px so neither
           overlaps if the inline slot is missing. */
        position: fixed; top: 52px; right: 20px; z-index: 999;
        background: linear-gradient(135deg, #0d6efd, #20c997);
        color: white; border: none; border-radius: 22px;
        padding: 8px 14px; font-size: 13px; font-weight: 600;
        cursor: pointer; box-shadow: 0 2px 10px rgba(13, 110, 253, 0.4);
        transition: transform .15s ease, box-shadow .15s ease;
      }
      #sc-cal-btn:hover { transform: translateY(-1px);
        box-shadow: 0 4px 14px rgba(13, 110, 253, 0.55); }
      #sc-cal-btn[data-pending="0"] { display: none; }
      #sc-cal-btn.sc-cal-btn--inline {
        position: static; margin: 0 8px; display: inline-flex;
        align-items: center; gap: 6px;
      }
      #sc-cal-btn .sc-cal-badge {
        display: inline-block; margin-left: 6px; background: #fff;
        color: #0d6efd; border-radius: 12px; padding: 1px 8px;
        font-weight: 700; font-size: 11px;
      }
      .sc-cal-overlay {
        position: fixed; inset: 0; z-index: 1000;
        background: rgba(5, 3, 15, 0.85); backdrop-filter: blur(6px);
        display: flex; align-items: center; justify-content: center;
      }
      .sc-cal-modal {
        background: #0f1420; color: #e8e6f5; border-radius: 14px;
        width: 94%; max-width: 1200px; max-height: 90vh; overflow: auto;
        border: 1px solid rgba(13, 110, 253, 0.5);
        box-shadow: 0 10px 40px rgba(0,0,0,0.6);
      }
      .sc-cal-header {
        padding: 18px 24px; border-bottom: 1px solid #1f2a3d;
        display: flex; align-items: center; justify-content: space-between;
      }
      .sc-cal-header h2 { margin: 0; font-size: 18px; color: #4dabf7; }
      .sc-cal-header small { color: #8ea0bf; font-size: 12px; margin-left: 8px; }
      .sc-cal-close {
        background: none; border: 0; color: #8ea0bf; font-size: 22px;
        cursor: pointer; padding: 4px 10px;
      }
      .sc-cal-close:hover { color: #4dabf7; }
      .sc-cal-body { padding: 18px 24px; }
      .sc-cal-bar {
        display: flex; align-items: center; gap: 12px; margin-bottom: 16px;
      }
      .sc-cal-progress {
        flex: 1; height: 8px; border-radius: 4px; background: #1f2a3d; overflow: hidden;
      }
      .sc-cal-progress > div {
        height: 100%; background: linear-gradient(90deg, #0d6efd, #20c997); width: 0%;
        transition: width .3s ease;
      }
      .sc-cal-actions { display: flex; gap: 8px; }
      .sc-cal-btn-primary {
        background: linear-gradient(135deg, #0d6efd, #20c997);
        color: white; border: 0; border-radius: 6px; padding: 8px 14px;
        font-size: 13px; font-weight: 600; cursor: pointer;
      }
      .sc-cal-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
      .sc-cal-btn-secondary {
        background: transparent; color: #4dabf7; border: 1px solid #4dabf7;
        border-radius: 6px; padding: 7px 13px; font-size: 13px; cursor: pointer;
      }
      .sc-cal-btn-danger {
        background: #b02a37; color: white; border: 0;
        border-radius: 6px; padding: 7px 13px; font-size: 13px; cursor: pointer;
        font-weight: 600;
      }
      .sc-cal-btn-danger:hover { background: #c0303d; }
      .sc-cal-btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }
      .sc-cal-grid {
        display: grid; gap: 16px;
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      }
      .sc-cal-card {
        background: #141c2b; border: 1px solid #1f2a3d; border-radius: 10px;
        padding: 10px; display: flex; flex-direction: column; gap: 8px;
      }
      .sc-cal-card.sc-cal-confirmed { border-color: #20c997; box-shadow: 0 0 0 1px #20c997 inset; }
      .sc-cal-card.sc-cal-failed { border-color: #e03131; }
      .sc-cal-thumb {
        width: 100%; aspect-ratio: 1/1; background: #0a0e16; border-radius: 6px;
        display: flex; align-items: center; justify-content: center; overflow: hidden;
      }
      .sc-cal-thumb img { width: 100%; height: 100%; object-fit: cover; }
      .sc-cal-thumb .sc-cal-err {
        color: #e03131; font-size: 12px; padding: 12px; text-align: center;
      }
      .sc-cal-name {
        font-size: 12px; color: #e8e6f5; word-break: break-word;
        font-family: 'Consolas', monospace;
      }
      .sc-cal-nsfw {
        display: inline-block; margin-left: 6px; padding: 1px 6px;
        border-radius: 4px; background: #e8590c; color: white;
        font-size: 10px; font-weight: 700; vertical-align: middle;
      }
      .sc-cal-chips { display: flex; flex-wrap: wrap; gap: 4px; }
      .sc-cal-chip {
        padding: 2px 8px; border-radius: 10px; font-size: 11px;
        background: #1f2a3d; color: #d9e1ed; border: 1px solid #2d3b54;
      }
      .sc-cal-chip[data-src="civitai"],
      .sc-cal-chip[data-src="civitai_sidecar"] { border-color: #4dabf7; color: #4dabf7; }
      .sc-cal-chip[data-src="shipped"] { border-color: #20c997; color: #20c997; }
      .sc-cal-chip[data-src="user"]    { border-color: #ffd700; color: #ffd700; }
      .sc-cal-chip[data-src="heuristic"], .sc-cal-chip[data-src="safetensors"] {
        border-color: #8ea0bf; color: #8ea0bf;
      }
      .sc-cal-triggers {
        font-size: 11px; color: #8ea0bf; font-style: italic;
        word-break: break-word; line-height: 1.35;
      }
      .sc-cal-row {
        display: flex; gap: 6px; margin-top: auto;
      }
      .sc-cal-confirm {
        flex: 1; background: #20c997; color: white; border: 0;
        border-radius: 6px; padding: 7px; font-size: 12px;
        font-weight: 600; cursor: pointer;
      }
      .sc-cal-confirm:disabled { opacity: 0.6; cursor: not-allowed; background: #0f5132; }
      .sc-cal-customize {
        background: transparent; color: #8ea0bf; border: 1px solid #2d3b54;
        border-radius: 6px; padding: 6px 10px; font-size: 12px; cursor: pointer;
      }
      .sc-cal-customize:hover { color: #4dabf7; border-color: #4dabf7; }
      .sc-cal-empty {
        text-align: center; padding: 40px; color: #8ea0bf; font-style: italic;
      }
      .sc-cal-skipped {
        margin-bottom: 14px; padding: 10px 12px; border-radius: 8px;
        background: #1a1f2e; border: 1px solid #2d3b54;
        color: #8ea0bf; font-size: 12px;
      }
      .sc-cal-skipped-head {
        font-weight: 600; color: #d9e1ed; display: flex;
        align-items: center; justify-content: space-between; cursor: pointer;
      }
      .sc-cal-skipped-head .sc-cal-chev {
        transition: transform .15s ease; display: inline-block;
      }
      .sc-cal-skipped.sc-cal-open .sc-cal-chev { transform: rotate(90deg); }
      .sc-cal-skipped-list {
        display: none; margin-top: 8px; max-height: 180px; overflow-y: auto;
      }
      .sc-cal-skipped.sc-cal-open .sc-cal-skipped-list { display: block; }
      .sc-cal-skipped-list li {
        list-style: none; padding: 2px 0; font-family: 'Consolas', monospace;
      }
      .sc-cal-skipped-list .sc-cal-skipped-reason {
        color: #e8590c; font-family: system-ui, sans-serif;
        font-style: italic; margin-left: 8px;
      }
    `;
    document.head.appendChild(s);
  }

  // ── State ─────────────────────────────────────────────────────────────
  const state = {
    summary: null,
    jobId: null,
    samples: [],            // live-streamed from poller
    confirmed: new Set(),   // lora names we've confirmed this session
    polling: false,
  };

  // ── HTTP helpers ──────────────────────────────────────────────────────
  async function api(path, opts) {
    const r = await fetch(path, Object.assign({
      headers: { 'Content-Type': 'application/json' },
    }, opts || {}));
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try { const j = await r.json(); if (j.error) msg = j.error; } catch {}
      throw new Error(msg);
    }
    return r.json();
  }

  async function fetchSummary() {
    try { return await api('/api/spellcaster/lora/calibrate/summary'); }
    catch { return null; }
  }

  async function startAuto(useNetwork) {
    return api('/api/spellcaster/lora/calibrate/auto/start', {
      method: 'POST',
      body: JSON.stringify({ subset: 'unconfirmed', use_network: !!useNetwork }),
    });
  }

  async function pollStatus(jobId) {
    return api('/api/spellcaster/lora/calibrate/auto/status?job=' + encodeURIComponent(jobId));
  }

  async function cancelJob(jobId) {
    return api('/api/spellcaster/lora/calibrate/auto/cancel?job=' + encodeURIComponent(jobId), {
      method: 'POST', body: '{}',
    });
  }

  async function confirmLora(payload) {
    return api('/api/spellcaster/lora/calibrate/confirm', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  // ── Button ────────────────────────────────────────────────────────────
  //
  // Layout: we want the button order in #chat-shootout-slot to be
  //     [Shootouts]  [Auto-calibrate]  [Turbo]
  // The Shootouts button is injected by lora_shootout.js (appended
  // into the slot). The Turbo button (#global-preset-btn) is
  // hardcoded in index.html, always present. So "between them"
  // means: insertBefore(#global-preset-btn).
  //
  // This function is both create-on-first-call AND re-place-on-
  // every-call: if some later DOM change orphans the button (splash
  // screen rerenders, slot gets replaced), we snap it back into the
  // right spot.
  function ensureButton() {
    let btn = document.getElementById('sc-cal-btn');
    const slot = document.getElementById('chat-shootout-slot');
    if (!btn) {
      btn = document.createElement('button');
      btn.id = 'sc-cal-btn';
      btn.setAttribute('data-pending', '0');
      btn.innerHTML = '✨ Auto-calibrate<span class="sc-cal-badge">0</span>';
      btn.addEventListener('click', openModal);
    }
    if (slot) {
      btn.classList.add('sc-cal-btn--inline');
      const turbo = slot.querySelector('#global-preset-btn');
      if (turbo && turbo.previousSibling !== btn) {
        slot.insertBefore(btn, turbo);
      } else if (!turbo && btn.parentNode !== slot) {
        slot.appendChild(btn);
      }
    } else if (btn.parentNode !== document.body) {
      btn.classList.remove('sc-cal-btn--inline');
      document.body.appendChild(btn);
    }
    return btn;
  }

  async function refreshButton() {
    const btn = ensureButton();
    const sum = await fetchSummary();
    state.summary = sum;
    const n = (sum && sum.registry_unconfirmed) || 0;
    btn.setAttribute('data-pending', String(n));
    const badge = btn.querySelector('.sc-cal-badge');
    if (badge) badge.textContent = String(n);
  }

  // ── Modal ─────────────────────────────────────────────────────────────
  function openModal() {
    const overlay = document.createElement('div');
    overlay.className = 'sc-cal-overlay';
    overlay.innerHTML = `
      <div class="sc-cal-modal">
        <div class="sc-cal-header">
          <div>
            <h2>Auto-calibrate LoRAs</h2>
            <small>One sample per LoRA using its Civitai-recommended recipe.</small>
          </div>
          <button class="sc-cal-close" title="Close">×</button>
        </div>
        <div class="sc-cal-body">
          <div class="sc-cal-bar">
            <div class="sc-cal-progress"><div></div></div>
            <div class="sc-cal-status" style="font-size:12px;color:#8ea0bf;min-width:130px"></div>
            <div class="sc-cal-actions">
              <label style="font-size:12px;color:#8ea0bf;display:flex;align-items:center;gap:4px">
                <input type="checkbox" class="sc-cal-network" checked> Civitai lookup
              </label>
              <button class="sc-cal-btn-secondary sc-cal-confirm-all" disabled>Confirm all visible</button>
              <button class="sc-cal-btn-danger sc-cal-cancel" style="display:none">⏹ Cancel</button>
              <button class="sc-cal-btn-primary sc-cal-start">Start</button>
            </div>
          </div>
          <div class="sc-cal-skipped" style="display:none"></div>
          <div class="sc-cal-grid sc-cal-grid-el"></div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const qs = (sel) => overlay.querySelector(sel);
    const grid = qs('.sc-cal-grid-el');
    const statusEl = qs('.sc-cal-status');
    const progress = qs('.sc-cal-progress > div');
    const startBtn = qs('.sc-cal-start');
    const confirmAllBtn = qs('.sc-cal-confirm-all');
    const cancelBtn = qs('.sc-cal-cancel');
    const networkChk = qs('.sc-cal-network');

    function close() { overlay.remove(); state.polling = false; refreshButton(); }
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    qs('.sc-cal-close').addEventListener('click', close);

    function setStatus(text) { statusEl.textContent = text; }
    function setProgress(done, total) {
      const pct = total > 0 ? Math.round((done * 100) / total) : 0;
      progress.style.width = pct + '%';
    }

    function chipsFor(rec) {
      const prov = rec.provenance || {};
      const parts = [];
      if (rec.strength != null) {
        parts.push({ label: 'w=' + Number(rec.strength).toFixed(2),
                     src: prov.recommended_weight || 'heuristic' });
      }
      if (rec.sampler) {
        parts.push({ label: rec.sampler, src: prov.recommended_sampler || 'shipped' });
      }
      if (rec.cfg != null) {
        parts.push({ label: 'cfg=' + Number(rec.cfg).toFixed(1),
                     src: prov.recommended_cfg || 'heuristic' });
      }
      if (rec.subject) {
        parts.push({ label: rec.subject, src: 'shipped' });
      }
      return parts.map(p =>
        `<span class="sc-cal-chip" data-src="${p.src}" title="from ${p.src}">${p.label}</span>`
      ).join('');
    }

    function renderCard(rec) {
      const id = 'sc-cal-card-' + rec.lora_name.replace(/[^a-z0-9]/gi, '_');
      let el = grid.querySelector('#' + CSS.escape(id));
      if (!el) {
        el = document.createElement('div');
        el.id = id;
        el.className = 'sc-cal-card';
        grid.appendChild(el);
      }
      const ok = !!rec.ok;
      const failed = !ok;
      el.classList.toggle('sc-cal-failed', failed);
      const nsfwTag = rec.nsfw ? '<span class="sc-cal-nsfw" title="classified NSFW — writes to NSFW store">NSFW</span>' : '';
      const civ = rec.knowledge && rec.knowledge.civitai_url
          ? `<a href="${rec.knowledge.civitai_url}" target="_blank" style="color:#4dabf7;font-size:11px">civitai</a>`
          : '';
      const trig = (rec.trigger_words || []).join(', ');
      el.innerHTML = `
        <div class="sc-cal-thumb">
          ${ok
            ? `<img src="data:image/png;base64,${rec.image_b64}" alt="${rec.lora_name}"/>`
            : `<div class="sc-cal-err">${(rec.error || 'no sample').toString()}</div>`}
        </div>
        <div class="sc-cal-name">${rec.lora_name}${nsfwTag}</div>
        <div class="sc-cal-chips">${chipsFor(rec)}</div>
        ${trig ? `<div class="sc-cal-triggers">triggers: ${trig}</div>` : ''}
        <div class="sc-cal-row">
          <button class="sc-cal-confirm" ${failed ? 'disabled' : ''}>✓ Confirm</button>
          <button class="sc-cal-customize" title="Open manual shootout">⚙</button>
          ${civ ? `<span style="align-self:center">${civ}</span>` : ''}
        </div>
      `;
      el.querySelector('.sc-cal-confirm').addEventListener('click', () => doConfirm(rec, el));
      el.querySelector('.sc-cal-customize').addEventListener('click', () => handOffToShootout(rec));
      if (state.confirmed.has(rec.lora_name)) markConfirmed(el);
    }

    function markConfirmed(el) {
      el.classList.add('sc-cal-confirmed');
      const b = el.querySelector('.sc-cal-confirm');
      if (b) { b.disabled = true; b.textContent = '✓ Confirmed'; }
    }

    async function doConfirm(rec, el) {
      const btn = el.querySelector('.sc-cal-confirm');
      if (btn) { btn.disabled = true; btn.textContent = 'Confirming…'; }
      try {
        await confirmLora({
          lora_name: rec.lora_name,
          strength: rec.strength,
          sampler: rec.sampler || undefined,
          cfg: rec.cfg,
          subject_key: rec.subject || undefined,
          trigger_words: rec.trigger_words || undefined,
          base_model: (rec.knowledge && rec.knowledge.base_model) || rec.arch || undefined,
          sha256: (rec.knowledge && rec.knowledge.sha256) || undefined,
          nsfw: !!rec.nsfw,
          source: 'auto_calibrate',
        });
        state.confirmed.add(rec.lora_name);
        markConfirmed(el);
      } catch (e) {
        if (btn) {
          btn.disabled = false; btn.textContent = '✓ Confirm';
          btn.title = String(e);
        }
      }
    }

    function handOffToShootout(rec) {
      // Defer to the existing shootout UI if present; otherwise just
      // alert the LoRA name so the user knows where to click.
      const hook = window.__sc_openShootoutFor;
      if (typeof hook === 'function') {
        hook({ arch: rec.arch, purpose_group: rec.purpose_group, lora: rec.lora_name });
      } else {
        const btn = document.getElementById('sc-shootout-btn');
        if (btn) btn.click();
      }
    }

    async function confirmAllVisible() {
      const cards = [...grid.querySelectorAll('.sc-cal-card:not(.sc-cal-confirmed):not(.sc-cal-failed)')];
      confirmAllBtn.disabled = true;
      confirmAllBtn.textContent = `Confirming ${cards.length}…`;
      for (const c of cards) {
        const btn = c.querySelector('.sc-cal-confirm');
        if (btn) btn.click();
        await new Promise((r) => setTimeout(r, 80)); // tiny stagger — avoids burst
      }
      confirmAllBtn.textContent = 'Confirm all visible';
      confirmAllBtn.disabled = false;
    }
    confirmAllBtn.addEventListener('click', confirmAllVisible);

    async function startJob() {
      startBtn.disabled = true; startBtn.textContent = 'Starting…';
      grid.innerHTML = '';
      state.samples = [];
      state.confirmed.clear();
      try {
        const resp = await startAuto(networkChk.checked);
        state.jobId = resp.job_id;
        setStatus(`rendering 1/${resp.total}…`);
        setProgress(0, resp.total);
        cancelBtn.style.display = '';
        cancelBtn.disabled = false;
        cancelBtn.textContent = '⏹ Cancel';
        pollLoop(resp.total);
      } catch (e) {
        setStatus('start failed: ' + e);
        startBtn.disabled = false; startBtn.textContent = 'Start';
      }
    }
    startBtn.addEventListener('click', startJob);

    async function cancelCurrentJob() {
      if (!state.jobId) return;
      cancelBtn.disabled = true;
      cancelBtn.textContent = 'Cancelling…';
      try {
        const r = await cancelJob(state.jobId);
        const warn = (r.comfy && r.comfy.errors && r.comfy.errors.length)
          ? ' (ComfyUI: ' + r.comfy.errors.join(', ') + ')' : '';
        setStatus('cancel requested' + warn);
      } catch (e) {
        setStatus('cancel failed: ' + e);
        cancelBtn.disabled = false;
        cancelBtn.textContent = '⏹ Cancel';
      }
    }
    cancelBtn.addEventListener('click', cancelCurrentJob);

    function renderSkipped(list) {
      const host = qs('.sc-cal-skipped');
      if (!host) return;
      if (!list || !list.length) { host.style.display = 'none'; return; }
      // Group by reason so a long list collapses to one row per reason.
      const byReason = {};
      for (const s of list) {
        const r = s.reason || 'skipped';
        (byReason[r] ||= []).push(s);
      }
      const lines = Object.entries(byReason).map(([reason, entries]) => {
        const names = entries.map(e => `<li>${e.lora_name}</li>`).join('');
        return `<div style="margin-bottom:6px"><strong style="color:#e8590c">${reason}</strong> — ${entries.length} LoRA${entries.length === 1 ? '' : 's'}<ul>${names}</ul></div>`;
      }).join('');
      host.innerHTML = `
        <div class="sc-cal-skipped-head">
          <span>${list.length} LoRA${list.length === 1 ? '' : 's'} skipped — click for details</span>
          <span class="sc-cal-chev">▸</span>
        </div>
        <div class="sc-cal-skipped-list">${lines}</div>
      `;
      host.style.display = 'block';
      const head = host.querySelector('.sc-cal-skipped-head');
      head.addEventListener('click', () => host.classList.toggle('sc-cal-open'));
    }

    async function pollLoop(total) {
      state.polling = true;
      while (state.polling) {
        await new Promise((r) => setTimeout(r, 2000));
        if (!state.polling) break;
        let s;
        try { s = await pollStatus(state.jobId); }
        catch (e) { setStatus('poll error: ' + e); continue; }
        setStatus(`${s.done}/${s.total} — ${s.current || '…'}`);
        setProgress(s.done, s.total);
        // Render any new samples (worker appends to list as it goes).
        const rendered = state.samples.length;
        for (let i = rendered; i < (s.samples || []).length; i++) {
          renderCard(s.samples[i]);
          state.samples.push(s.samples[i]);
        }
        // Skipped list is computed once at job start, but render it
        // on every tick in case it arrives on a later poll.
        if (s.skipped && s.skipped.length) renderSkipped(s.skipped);
        if (s.status !== 'running') {
          const skipTag = (s.skipped && s.skipped.length)
            ? `, ${s.skipped.length} skipped` : '';
          setStatus(`${s.status} — ${s.done}/${s.total}${skipTag}`);
          state.polling = false;
          confirmAllBtn.disabled = false;
          startBtn.disabled = false;
          startBtn.textContent = (s.status === 'complete' || s.status === 'cancelled')
            ? 'Re-run' : 'Start';
          cancelBtn.style.display = 'none';
        }
      }
    }

    // Initial summary display before the user hits Start.
    (async () => {
      const sum = state.summary || await fetchSummary();
      const total = (sum && sum.registry_total) || 0;
      const confirmed = (sum && sum.registry_confirmed) || 0;
      const pending = (sum && sum.registry_unconfirmed) || 0;
      setStatus(`${pending} unconfirmed · ${confirmed}/${total} done`);
      if (pending === 0) {
        grid.innerHTML = '<div class="sc-cal-empty">Every LoRA is confirmed. Nothing to do.</div>';
        startBtn.disabled = true;
      }
    })();
  }

  // ── Boot ──────────────────────────────────────────────────────────────
  function boot() { refreshButton(); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }
  // Re-check every 60s so the badge count stays fresh.
  setInterval(refreshButton, 60000);

  // Public hook for other modules.
  window.__sc_autoCalibrate = { refresh: refreshButton, open: openModal };
})();
