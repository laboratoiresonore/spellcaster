/*  Calibration — one-stop LoRA tuning studio.
 *
 *  Merges the old "⚔ Shootouts" (manual A/B between duplicates) and
 *  "✨ Auto-calibrate" (Civitai-driven recipe confirmation) into a
 *  single modal with three tabs:
 *
 *    Confirm   — auto-rendered cards grouped by (arch, purpose_group)
 *                with per-card ✓ Confirm and optional LLM auto-confirm
 *    Compare   — the legacy shootouts UI, reachable either from this
 *                tab or from the "⚔ Compare" chip on a group header
 *    Stats     — coverage + scorer availability
 *
 *  The legacy shootouts button injection is disabled (see
 *  lora_shootout.js::ensureEntryButton). Legacy keyboard / console
 *  entry points still work via window.SpellcasterShootout.open().
 *
 *  Backend endpoints used:
 *    GET  /api/spellcaster/lora/calibrate/summary
 *    GET  /api/spellcaster/lora/groups
 *    GET  /api/spellcaster/lora/scorer/probe
 *    POST /api/spellcaster/lora/calibrate/auto/start
 *    GET  /api/spellcaster/lora/calibrate/auto/status?job=
 *    POST /api/spellcaster/lora/calibrate/auto/cancel?job=
 *    POST /api/spellcaster/lora/calibrate/confirm
 */
(function () {
  'use strict';

  // ── Style injection ──────────────────────────────────────────────────
  const STYLE_ID = 'sc-calib-style';
  if (!document.getElementById(STYLE_ID)) {
    const s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = `
      #sc-calib-btn {
        position: fixed; top: 14px; right: 20px; z-index: 999;
        background: linear-gradient(135deg, #8a2be2, #4dabf7);
        color: white; border: none; border-radius: 22px;
        padding: 8px 14px; font-size: 13px; font-weight: 600;
        cursor: pointer; box-shadow: 0 2px 10px rgba(138, 43, 226, 0.4);
        transition: transform .15s ease, box-shadow .15s ease;
      }
      #sc-calib-btn:hover { transform: translateY(-1px);
        box-shadow: 0 4px 14px rgba(138, 43, 226, 0.6); }
      #sc-calib-btn.sc-calib-btn--inline {
        position: static; margin: 0 8px; display: inline-flex;
        align-items: center; gap: 6px;
      }
      #sc-calib-btn .sc-calib-badge {
        display: inline-block; margin-left: 6px; background: #fff;
        color: #8a2be2; border-radius: 12px; padding: 1px 8px;
        font-weight: 700; font-size: 11px;
      }
      #sc-calib-btn .sc-calib-badge.sc-calib-ok { background:#20c997; color:white; }

      /* Preflight status dot sits immediately left of the Calibration
         button so the user sees the whole-system health at a glance:
         green=ready, yellow=degraded (auto-recovering / no preflight
         run yet), red=broken (ComfyUI down / arch canary failed /
         faceswap escalated), gray=unknown. */
      #sc-preflight-dot {
        display: inline-flex; align-items: center; justify-content: center;
        width: 12px; height: 12px; border-radius: 50%;
        background: #6c757d;             /* default: unknown/gray */
        margin-right: 6px;
        cursor: pointer;
        box-shadow: 0 0 0 2px rgba(255,255,255,0.08);
        vertical-align: middle;
        position: relative;
        flex-shrink: 0;
        transition: background .2s ease, box-shadow .2s ease;
      }
      #sc-preflight-dot[data-state="green"]   { background: #20c997;
        box-shadow: 0 0 0 2px rgba(32,201,151,0.25); }
      #sc-preflight-dot[data-state="yellow"]  { background: #ffc107;
        box-shadow: 0 0 0 2px rgba(255,193,7,0.25); }
      #sc-preflight-dot[data-state="red"]     { background: #e03131;
        box-shadow: 0 0 0 2px rgba(224,49,49,0.3); }
      #sc-preflight-dot[data-running="1"]::after {
        content: ''; position: absolute; inset: -4px;
        border: 2px solid rgba(77,171,247,0.7);
        border-top-color: transparent; border-radius: 50%;
        animation: sc-preflight-spin 1s linear infinite;
      }
      @keyframes sc-preflight-spin { to { transform: rotate(360deg); } }
      #sc-preflight-dot:hover { filter: brightness(1.15); }

      .sc-calib-overlay {
        position: fixed; inset: 0; z-index: 1000;
        background: rgba(5, 3, 15, 0.85); backdrop-filter: blur(6px);
        display: flex; align-items: center; justify-content: center;
      }
      .sc-calib-modal {
        background: #0f1420; color: #e8e6f5; border-radius: 14px;
        width: 96%; max-width: 1280px; max-height: 92vh;
        display: flex; flex-direction: column;
        border: 1px solid rgba(138, 43, 226, 0.45);
        box-shadow: 0 10px 40px rgba(0,0,0,0.6);
      }
      .sc-calib-head {
        padding: 16px 24px; border-bottom: 1px solid #1f2a3d;
        display: flex; align-items: center; justify-content: space-between;
      }
      .sc-calib-head h2 { margin: 0; font-size: 18px;
        background: linear-gradient(90deg,#8a2be2,#4dabf7);
        -webkit-background-clip: text; background-clip: text;
        -webkit-text-fill-color: transparent;
      }
      .sc-calib-head small { color:#8ea0bf; font-size:12px; margin-left:8px }
      .sc-calib-close {
        background: none; border: 0; color: #8ea0bf; font-size: 22px;
        cursor: pointer; padding: 4px 10px;
      }
      .sc-calib-close:hover { color: #e8e6f5; }

      .sc-calib-tabs {
        display: flex; gap: 4px; padding: 0 18px;
        border-bottom: 1px solid #1f2a3d; flex-shrink: 0;
      }
      .sc-calib-tab {
        background: none; border: 0; color: #8ea0bf;
        padding: 10px 14px; font-size: 13px; cursor: pointer;
        border-bottom: 2px solid transparent; font-weight: 600;
      }
      .sc-calib-tab.active { color: #e8e6f5;
        border-bottom-color: #8a2be2; }
      .sc-calib-tab:hover { color: #e8e6f5; }
      .sc-calib-tab .sc-calib-tab-count {
        margin-left: 6px; background: #1f2a3d; color: #d9e1ed;
        padding: 1px 8px; border-radius: 10px; font-size: 11px;
      }

      .sc-calib-body {
        padding: 16px 24px; overflow-y: auto; flex: 1;
      }
      .sc-calib-bar {
        display: flex; align-items: center; gap: 12px; margin-bottom: 14px;
        flex-wrap: wrap;
      }
      .sc-calib-progress {
        flex: 1; min-width: 200px; height: 8px;
        border-radius: 4px; background: #1f2a3d; overflow: hidden;
      }
      .sc-calib-progress > div {
        height: 100%; width: 0%;
        background: linear-gradient(90deg, #8a2be2, #4dabf7);
        transition: width .3s ease;
      }
      .sc-calib-status {
        font-size: 12px; color: #8ea0bf; min-width: 180px;
      }
      .sc-calib-actions { display: flex; gap: 6px; flex-wrap: wrap; }

      .sc-calib-btn-primary {
        background: linear-gradient(135deg, #8a2be2, #4dabf7);
        color: white; border: 0; border-radius: 6px;
        padding: 7px 14px; font-size: 13px; font-weight: 600;
        cursor: pointer;
      }
      .sc-calib-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
      .sc-calib-btn-secondary {
        background: transparent; color: #4dabf7; border: 1px solid #4dabf7;
        border-radius: 6px; padding: 6px 12px; font-size: 12px; cursor: pointer;
      }
      .sc-calib-btn-secondary:disabled { opacity: 0.4; cursor: not-allowed; }
      .sc-calib-btn-danger {
        background: #b02a37; color: white; border: 0;
        border-radius: 6px; padding: 7px 12px; font-size: 12px; cursor: pointer;
        font-weight: 600;
      }
      .sc-calib-btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }

      .sc-calib-scorer {
        display: flex; align-items: center; gap: 10px;
        padding: 8px 12px; border-radius: 8px;
        background: #1a1f2e; border: 1px solid #2d3b54;
        font-size: 12px; color: #8ea0bf;
      }
      .sc-calib-scorer label { display: flex; align-items: center; gap: 5px;
        cursor: pointer; color: #e8e6f5; }
      .sc-calib-scorer input[type=number] {
        width: 50px; background: #0a0e16; color: #e8e6f5;
        border: 1px solid #2d3b54; border-radius: 4px; padding: 3px 5px;
      }
      .sc-calib-scorer.disabled { opacity: 0.5; pointer-events: none; }

      .sc-calib-opts {
        display: flex; flex-wrap: wrap; gap: 6px;
        padding: 8px 12px; border-radius: 8px;
        background: #1a1f2e; border: 1px solid #2d3b54;
        font-size: 12px; color: #e8e6f5;
      }
      .sc-calib-opts label {
        display: flex; align-items: center; gap: 5px; cursor: pointer;
      }
      .sc-calib-opts label.disabled { opacity: 0.4; cursor: not-allowed; }

      .sc-calib-resume {
        margin-bottom: 14px; padding: 10px 14px; border-radius: 8px;
        background: linear-gradient(90deg,
          rgba(138,43,226,0.15), rgba(77,171,247,0.15));
        border: 1px solid rgba(138,43,226,0.4);
        display: flex; align-items: center; gap: 12px; font-size: 13px;
      }
      .sc-calib-resume .msg { flex: 1; color: #e8e6f5; }
      .sc-calib-resume .sc-calib-btn-secondary { border-color:#8a2be2; color:#d4bfff; }

      .sc-calib-badge-inline {
        display: inline-block; padding: 1px 6px; border-radius: 10px;
        font-size: 10px; font-weight: 700; margin-left: 4px;
      }
      .sc-calib-badge-inline.unstable {
        background: rgba(255,193,7,0.85); color: #0a0e16;
      }
      .sc-calib-badge-inline.sweep {
        background: rgba(77,171,247,0.85); color: white;
      }

      .sc-calib-skipped {
        margin-bottom: 14px; padding: 10px 12px; border-radius: 8px;
        background: #1a1f2e; border: 1px solid #2d3b54;
        color: #8ea0bf; font-size: 12px;
      }
      .sc-calib-skipped-head {
        font-weight: 600; color: #d9e1ed; display: flex;
        align-items: center; justify-content: space-between; cursor: pointer;
      }
      .sc-calib-skipped.open .sc-calib-chev { transform: rotate(90deg); }
      .sc-calib-chev { transition: transform .15s ease; display: inline-block; }
      .sc-calib-skipped-list { display: none; margin-top: 8px;
        max-height: 180px; overflow-y: auto; }
      .sc-calib-skipped.open .sc-calib-skipped-list { display: block; }

      .sc-calib-group {
        margin-bottom: 20px;
      }
      .sc-calib-group-head {
        display: flex; align-items: center; gap: 10px;
        padding: 8px 4px; border-bottom: 1px solid #1f2a3d;
        margin-bottom: 10px;
      }
      .sc-calib-group-title {
        font-weight: 600; color: #e8e6f5; font-size: 13px;
      }
      .sc-calib-group-meta {
        font-size: 11px; color: #8ea0bf;
      }
      .sc-calib-compare-chip {
        margin-left: auto;
        background: transparent; color: #ffd700; border: 1px solid #ffd700;
        border-radius: 12px; padding: 3px 10px; font-size: 11px;
        font-weight: 600; cursor: pointer;
      }
      .sc-calib-compare-chip:hover { background: rgba(255,215,0,0.1); }

      .sc-calib-grid {
        display: grid; gap: 14px;
        grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
      }
      .sc-calib-card {
        background: #141c2b; border: 1px solid #1f2a3d; border-radius: 10px;
        padding: 10px; display: flex; flex-direction: column; gap: 6px;
      }
      .sc-calib-card.confirmed {
        border-color: #20c997;
        box-shadow: 0 0 0 1px #20c997 inset;
      }
      .sc-calib-card.failed { border-color: #e03131; }
      .sc-calib-card.auto-confirmed {
        border-color: #4dabf7;
        box-shadow: 0 0 0 1px #4dabf7 inset;
      }
      .sc-calib-thumb {
        width: 100%; aspect-ratio: 1/1; background: #0a0e16;
        border-radius: 6px; overflow: hidden; position: relative;
      }
      .sc-calib-thumb img { width: 100%; height: 100%; object-fit: cover; }
      .sc-calib-thumb.with-ref { display: flex; aspect-ratio: 2/1; }
      .sc-calib-thumb.with-ref img { width: 50%; height: 100%; }
      .sc-calib-thumb .sc-calib-ref {
        border-left: 2px solid #B246F2;
      }
      .sc-calib-thumb.with-ref::before {
        content: 'render'; position: absolute; top: 4px; left: 6px;
        font-size: 9px; color: #aaa; background: rgba(0,0,0,0.55);
        padding: 1px 5px; border-radius: 3px; pointer-events: none;
      }
      .sc-calib-thumb.with-ref::after {
        content: 'trainer'; position: absolute; top: 4px; right: 6px;
        font-size: 9px; color: #c4b5fd; background: rgba(0,0,0,0.55);
        padding: 1px 5px; border-radius: 3px; pointer-events: none;
      }
      .sc-calib-thumb .err {
        padding: 12px; color: #e03131; font-size: 11px; text-align: center;
      }
      .sc-calib-score-chip {
        position: absolute; top: 6px; right: 6px;
        padding: 2px 8px; border-radius: 12px;
        font-size: 11px; font-weight: 700;
        backdrop-filter: blur(4px);
      }
      .sc-calib-score-chip.good { background: rgba(32,201,151,0.9); color: white; }
      .sc-calib-score-chip.mid  { background: rgba(255,193,7,0.9); color: #0a0e16; }
      .sc-calib-score-chip.bad  { background: rgba(224,49,49,0.9); color: white; }
      .sc-calib-score-chip.pending { background: rgba(142,160,191,0.7); color: white; }

      .sc-calib-name {
        font-size: 12px; color: #e8e6f5; word-break: break-word;
        font-family: 'Consolas', monospace;
      }
      .sc-calib-nsfw {
        display: inline-block; margin-left: 6px; padding: 1px 6px;
        border-radius: 4px; background: #e8590c; color: white;
        font-size: 10px; font-weight: 700;
      }
      .sc-calib-chips { display: flex; flex-wrap: wrap; gap: 4px; }
      .sc-calib-chip {
        padding: 2px 8px; border-radius: 10px; font-size: 11px;
        background: #1f2a3d; color: #d9e1ed; border: 1px solid #2d3b54;
      }
      .sc-calib-chip[data-src="civitai"],
      .sc-calib-chip[data-src="civitai_sidecar"] { border-color:#4dabf7; color:#4dabf7; }
      .sc-calib-chip[data-src="shipped"] { border-color:#20c997; color:#20c997; }
      .sc-calib-chip[data-src="user"]    { border-color:#ffd700; color:#ffd700; }
      .sc-calib-chip[data-src="heuristic"],
      .sc-calib-chip[data-src="safetensors"] { border-color:#8ea0bf; color:#8ea0bf; }
      .sc-calib-trig {
        font-size: 11px; color: #8ea0bf; font-style: italic;
        word-break: break-word; line-height: 1.35;
      }
      .sc-calib-row { display: flex; gap: 6px; margin-top: auto; }
      .sc-calib-confirm-btn {
        flex: 1; background: #20c997; color: white; border: 0;
        border-radius: 6px; padding: 7px; font-size: 12px;
        font-weight: 600; cursor: pointer;
      }
      .sc-calib-confirm-btn:disabled { opacity: 0.6; cursor: not-allowed; background: #0f5132; }
      .sc-calib-custom-btn {
        background: transparent; color: #8ea0bf; border: 1px solid #2d3b54;
        border-radius: 6px; padding: 6px 10px; font-size: 12px; cursor: pointer;
      }
      .sc-calib-custom-btn:hover { color:#4dabf7; border-color:#4dabf7; }

      .sc-calib-empty {
        text-align: center; padding: 40px; color: #8ea0bf; font-style: italic;
      }
      .sc-calib-stats-grid {
        display: grid; gap: 10px;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        margin-bottom: 18px;
      }
      .sc-calib-stat {
        background: #141c2b; border: 1px solid #1f2a3d;
        border-radius: 8px; padding: 14px;
      }
      .sc-calib-stat-num {
        font-size: 28px; font-weight: 700; color: #e8e6f5;
      }
      .sc-calib-stat-label {
        font-size: 11px; color: #8ea0bf; margin-top: 3px;
      }
      .sc-calib-compare-list {
        display: flex; flex-direction: column; gap: 8px;
      }
      .sc-calib-compare-row {
        display: flex; align-items: center; justify-content: space-between;
        padding: 10px 14px; border-radius: 8px;
        background: #141c2b; border: 1px solid #1f2a3d;
      }
      .sc-calib-compare-row-title { color: #e8e6f5; font-weight: 600; }
      .sc-calib-compare-row-meta { color: #8ea0bf; font-size: 11px; margin-top: 2px; }
    `;
    document.head.appendChild(s);
  }

  // ── State ─────────────────────────────────────────────────────────────
  const state = {
    summary: null,
    groupsData: null,      // from /lora/groups
    scorer: null,          // from /scorer/probe
    jobId: null,
    samples: [],
    confirmed: new Set(),
    autoConfirmedNames: new Set(),
    polling: false,
    currentTab: 'confirm',
    activeOverlay: null,
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
  const safeApi = (p, o) => api(p, o).catch(() => null);

  // ── Preflight status dot ──────────────────────────────────────────────
  // Sits immediately left of the Calibration button. Reflects the
  // aggregated traffic light from /api/spellcaster/preflight/status.
  function ensurePreflightDot(slot) {
    let dot = document.getElementById('sc-preflight-dot');
    if (!dot) {
      dot = document.createElement('span');
      dot.id = 'sc-preflight-dot';
      dot.setAttribute('data-state', 'unknown');
      dot.setAttribute('role', 'button');
      dot.setAttribute('tabindex', '0');
      dot.title = 'System preflight: checking…';
      dot.addEventListener('click', () => {
        // Click the dot to open Calibration → Stats where the full
        // health breakdown + "Re-run preflight" button lives.
        if (state.currentTab !== 'stats') state.currentTab = 'stats';
        openModal();
      });
    }
    const calib = document.getElementById('sc-calib-btn');
    if (slot && calib && calib.previousSibling !== dot) {
      slot.insertBefore(dot, calib);
    } else if (!slot && dot.parentNode !== document.body) {
      dot.style.position = 'fixed';
      dot.style.top = '17px';
      dot.style.right = '200px';
      dot.style.zIndex = '999';
      document.body.appendChild(dot);
    }
    return dot;
  }

  async function refreshPreflightDot() {
    const dot = ensurePreflightDot(document.getElementById('chat-shootout-slot'));
    if (!dot) return;
    try {
      const r = await fetch('/api/spellcaster/preflight/status');
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      state.preflight = j;
      const s = j.overall || 'unknown';
      dot.setAttribute('data-state', s);
      const running = !!(j.run_job && j.run_job.running);
      dot.setAttribute('data-running', running ? '1' : '0');
      const bits = [j.headline || s];
      if (running) bits.push('(running: ' + (j.run_job.progress || '…') + ')');
      dot.title = bits.join(' ');
    } catch (e) {
      dot.setAttribute('data-state', 'unknown');
      dot.title = 'Preflight probe failed: ' + e;
    }
  }

  // ── Button ────────────────────────────────────────────────────────────
  function ensureButton() {
    let btn = document.getElementById('sc-calib-btn');
    const slot = document.getElementById('chat-shootout-slot');
    if (!btn) {
      btn = document.createElement('button');
      btn.id = 'sc-calib-btn';
      btn.title = 'Calibration — confirm LoRA recipes + compare duplicates';
      btn.innerHTML = '✧ Calibration<span class="sc-calib-badge">0</span>';
      btn.addEventListener('click', openModal);
    }
    if (slot) {
      btn.classList.add('sc-calib-btn--inline');
      const turbo = slot.querySelector('#global-preset-btn');
      if (turbo && btn !== turbo.previousSibling) {
        slot.insertBefore(btn, turbo);
      } else if (!turbo && btn.parentNode !== slot) {
        slot.appendChild(btn);
      }
    } else if (btn.parentNode !== document.body) {
      btn.classList.remove('sc-calib-btn--inline');
      document.body.appendChild(btn);
    }
    ensurePreflightDot(slot);
    return btn;
  }

  async function refreshButton() {
    const btn = ensureButton();
    const [summary, groups] = await Promise.all([
      safeApi('/api/spellcaster/lora/calibrate/summary'),
      safeApi('/api/spellcaster/lora/groups'),
    ]);
    state.summary = summary;
    state.groupsData = groups;
    const unconfirmed = (summary && summary.registry_unconfirmed) || 0;
    const compareGroups = (groups && groups.pending ? groups.pending.length : 0);
    const total = unconfirmed + compareGroups;
    const badge = btn.querySelector('.sc-calib-badge');
    if (badge) {
      badge.textContent = String(total);
      badge.classList.toggle('sc-calib-ok', total === 0);
    }
    refreshPreflightDot();
  }

  // ── Modal ─────────────────────────────────────────────────────────────
  function openModal() {
    if (state.activeOverlay) return;     // don't double-open
    const overlay = document.createElement('div');
    overlay.className = 'sc-calib-overlay';
    overlay.innerHTML = `
      <div class="sc-calib-modal">
        <div class="sc-calib-head">
          <div>
            <h2>✧ Calibration</h2>
            <small>Auto-tune LoRA recipes, pick winners between duplicates.</small>
          </div>
          <button class="sc-calib-close" title="Close">×</button>
        </div>
        <div class="sc-calib-tabs">
          <button class="sc-calib-tab" data-tab="confirm">
            Confirm <span class="sc-calib-tab-count tab-confirm-n">–</span>
          </button>
          <button class="sc-calib-tab" data-tab="compare">
            Compare duplicates <span class="sc-calib-tab-count tab-compare-n">–</span>
          </button>
          <button class="sc-calib-tab" data-tab="stats">Stats</button>
        </div>
        <div class="sc-calib-body sc-calib-body-el"></div>
      </div>
    `;
    document.body.appendChild(overlay);
    state.activeOverlay = overlay;

    const close = () => {
      overlay.remove();
      state.polling = false;
      state.activeOverlay = null;
      refreshButton();
    };
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    overlay.querySelector('.sc-calib-close').addEventListener('click', close);

    overlay.querySelectorAll('.sc-calib-tab').forEach((t) => {
      t.addEventListener('click', () => selectTab(t.dataset.tab));
    });

    bootstrap();
  }

  async function bootstrap() {
    // Lazy probe for the multimodal scorer so the UI can disable the
    // auto-confirm toggle when it's unreachable.
    state.scorer = await safeApi('/api/spellcaster/lora/scorer/probe');
    await refreshButton();
    updateTabCounts();
    selectTab(state.currentTab);
  }

  function updateTabCounts() {
    const overlay = state.activeOverlay;
    if (!overlay) return;
    const unconfirmed = (state.summary && state.summary.registry_unconfirmed) || 0;
    const pending = (state.groupsData && state.groupsData.pending
                      ? state.groupsData.pending.length : 0);
    const qs = overlay.querySelector.bind(overlay);
    qs('.tab-confirm-n').textContent = String(unconfirmed);
    qs('.tab-compare-n').textContent = String(pending);
  }

  function selectTab(tab) {
    state.currentTab = tab;
    const overlay = state.activeOverlay;
    if (!overlay) return;
    overlay.querySelectorAll('.sc-calib-tab').forEach((t) => {
      t.classList.toggle('active', t.dataset.tab === tab);
    });
    const body = overlay.querySelector('.sc-calib-body-el');
    body.innerHTML = '';
    if (tab === 'confirm')    return renderConfirmTab(body);
    if (tab === 'compare')    return renderCompareTab(body);
    if (tab === 'stats')      return renderStatsTab(body);
  }

  // ── CONFIRM tab ───────────────────────────────────────────────────────
  function renderConfirmTab(body) {
    const scorerOk = !!(state.scorer && state.scorer.ok);
    const scorerLabel = scorerOk
      ? `${state.scorer.model} ready`
      : `scorer unavailable${state.scorer && state.scorer.reason ? ': ' + state.scorer.reason : ''}`;
    body.innerHTML = `
      <div class="sc-calib-resume" style="display:none"></div>
      <div class="sc-calib-bar">
        <div class="sc-calib-progress"><div></div></div>
        <div class="sc-calib-status"></div>
        <div class="sc-calib-actions">
          <button class="sc-calib-btn-secondary sc-calib-confirm-all" disabled>Confirm all visible</button>
          <button class="sc-calib-btn-danger sc-calib-cancel" style="display:none">⏹ Cancel</button>
          <button class="sc-calib-btn-primary sc-calib-start">Start</button>
        </div>
      </div>
      <div class="sc-calib-opts">
        <label title="Before rendering every LoRA, probe each arch with a base sample. Archs that fail get all their LoRAs skipped with a clear reason instead of streaming red error cards.">
          <input type="checkbox" class="sc-calib-preflight" checked> Preflight per arch
        </label>
        <label title="Use the Civitai knowledge layer for triggers + weight + sampler recommendations.">
          <input type="checkbox" class="sc-calib-network" checked> Civitai
        </label>
        <label class="${scorerOk ? '' : 'disabled'}" title="Render each LoRA with 3 different seeds, flag those with scores that swing by more than 3 points as unstable. Needs the LLM scorer to be meaningful.">
          <input type="checkbox" class="sc-calib-stability" ${scorerOk ? '' : 'disabled'}> Stability check (3 seeds)
        </label>
        <label class="${scorerOk ? '' : 'disabled'}" title="For LoRAs with no Civitai-recommended weight, render at 0.4 / 0.7 / 1.0 and auto-pick the winner by score.">
          <input type="checkbox" class="sc-calib-sweep" ${scorerOk ? '' : 'disabled'}> Auto-weight sweep
        </label>
        <div class="sc-calib-scorer ${scorerOk ? '' : 'disabled'}" title="${scorerLabel}">
          <label><input type="checkbox" class="sc-calib-score" ${scorerOk ? '' : 'disabled'}> LLM auto-score</label>
          <span>≥</span>
          <input type="number" class="sc-calib-thresh" step="0.5" min="0" max="10" value="7.5">
        </div>
      </div>
      <div class="sc-calib-skipped" style="display:none"></div>
      <div class="sc-calib-groups"></div>
    `;

    const qs = (sel) => body.querySelector(sel);
    const progress = qs('.sc-calib-progress > div');
    const statusEl = qs('.sc-calib-status');
    const startBtn = qs('.sc-calib-start');
    const cancelBtn = qs('.sc-calib-cancel');
    const confirmAllBtn = qs('.sc-calib-confirm-all');
    const networkChk = qs('.sc-calib-network');
    const scoreChk = qs('.sc-calib-score');
    const threshInp = qs('.sc-calib-thresh');
    const preflightChk = qs('.sc-calib-preflight');
    const stabilityChk = qs('.sc-calib-stability');
    const sweepChk = qs('.sc-calib-sweep');
    const resumeEl = qs('.sc-calib-resume');
    const groupsEl = qs('.sc-calib-groups');
    const skippedEl = qs('.sc-calib-skipped');

    // Stability + sweep both need the scorer to be meaningful, so
    // turning off the scorer disables both toggles. Keeping the
    // dependency enforced in the UI rather than the backend so the
    // user sees immediate feedback.
    function reflectScorerGating() {
      const on = scoreChk.checked;
      for (const chk of [stabilityChk, sweepChk]) {
        if (!chk || !scorerOk) continue;
        chk.disabled = !on;
        chk.parentElement.classList.toggle('disabled', !on);
        if (!on) chk.checked = false;
      }
    }
    scoreChk.addEventListener('change', reflectScorerGating);
    reflectScorerGating();

    const setStatus = (t) => (statusEl.textContent = t);
    const setProgress = (done, total) => {
      const pct = total > 0 ? Math.round(done * 100 / total) : 0;
      progress.style.width = pct + '%';
    };

    function groupKey(arch, purpose) { return `${arch}::${purpose}`; }

    function ensureGroupBlock(arch, purpose) {
      const key = groupKey(arch, purpose);
      let block = groupsEl.querySelector(`[data-group="${CSS.escape(key)}"]`);
      if (block) return block;
      block = document.createElement('div');
      block.className = 'sc-calib-group';
      block.setAttribute('data-group', key);
      // Count candidates in that (arch, purpose) from the /groups data
      // so the chip can hand off to Compare when >1.
      const fullKey = (state.groupsData && state.groupsData.all && state.groupsData.all[key]) || null;
      const memberCount = fullKey ? fullKey.members.length : 1;
      const chip = memberCount > 1
        ? `<button class="sc-calib-compare-chip" data-arch="${arch}" data-purpose="${purpose}">⚔ Compare ${memberCount}</button>`
        : '';
      block.innerHTML = `
        <div class="sc-calib-group-head">
          <div>
            <div class="sc-calib-group-title">${(purpose || 'other').replace(/_/g, ' ')}</div>
            <div class="sc-calib-group-meta">${arch || 'unknown arch'}</div>
          </div>
          ${chip}
        </div>
        <div class="sc-calib-grid"></div>
      `;
      groupsEl.appendChild(block);
      const cc = block.querySelector('.sc-calib-compare-chip');
      if (cc) cc.addEventListener('click', () => selectTab('compare'));
      return block;
    }

    function chipsFor(s) {
      const p = s.provenance || {};
      const out = [];
      if (s.strength != null) {
        out.push({ label: 'w=' + Number(s.strength).toFixed(2),
                   src: p.recommended_weight || 'heuristic' });
      }
      if (s.sampler) out.push({ label: s.sampler, src: p.recommended_sampler || 'shipped' });
      if (s.cfg != null) {
        out.push({ label: 'cfg=' + Number(s.cfg).toFixed(1),
                   src: p.recommended_cfg || 'heuristic' });
      }
      if (s.subject) out.push({ label: s.subject, src: 'shipped' });
      return out.map(p =>
        `<span class="sc-calib-chip" data-src="${p.src}" title="from ${p.src}">${p.label}</span>`
      ).join('');
    }

    function scoreChip(s) {
      if (s.score_ok === false && s.score_error) {
        return `<span class="sc-calib-score-chip pending" title="${s.score_error}">?</span>`;
      }
      if (typeof s.score !== 'number') return '';
      const v = s.score;
      const klass = v >= 7 ? 'good' : (v >= 4 ? 'mid' : 'bad');
      const title = s.score_reason ? s.score_reason.replace(/"/g, '&quot;') : '';
      return `<span class="sc-calib-score-chip ${klass}" title="${title}">${v.toFixed(1)}</span>`;
    }

    function extraBadges(s) {
      const out = [];
      if (s.unstable) {
        const range = typeof s.stability_range === 'number'
          ? ` (±${s.stability_range.toFixed(1)})` : '';
        out.push(`<span class="sc-calib-badge-inline unstable" title="Score varied by more than 3 points across seeds${range}">⚠ unstable</span>`);
      }
      if (typeof s.sweep_winner === 'number') {
        const picks = (s.sweep_scores || []).map(r => {
          const sc = (typeof r.score === 'number') ? r.score.toFixed(1) : '—';
          return `${Number(r.strength).toFixed(2)}→${sc}`;
        }).join(' · ');
        out.push(`<span class="sc-calib-badge-inline sweep" title="Weight sweep picked ${Number(s.sweep_winner).toFixed(2)} from: ${picks}">⚙ sweep</span>`);
      }
      return out.join('');
    }

    function renderCard(rec) {
      const id = 'sc-calib-card-' + rec.lora_name.replace(/[^a-z0-9]/gi, '_');
      const block = ensureGroupBlock(rec.arch, rec.purpose_group);
      const grid = block.querySelector('.sc-calib-grid');
      let el = grid.querySelector('#' + CSS.escape(id));
      if (!el) {
        el = document.createElement('div');
        el.id = id;
        el.className = 'sc-calib-card';
        grid.appendChild(el);
      }
      const ok = !!rec.ok;
      el.classList.toggle('failed', !ok);
      const nsfwTag = rec.nsfw ? '<span class="sc-calib-nsfw">NSFW</span>' : '';
      const trigs = (rec.trigger_words || []).join(', ');
      const civ = rec.knowledge && rec.knowledge.civitai_url
          ? `<a href="${rec.knowledge.civitai_url}" target="_blank" style="color:#4dabf7;font-size:11px">civitai</a>`
          : '';
      // Side-by-side reference thumbnail when Civitai metadata gave us
      // a preview URL. The trainer's example is shown beside the render
      // so users have ground truth for the "did it work?" judgement.
      const refImg = rec.civitai_preview_b64
          ? `<img class="sc-calib-ref" src="data:image/*;base64,${rec.civitai_preview_b64}" alt="Civitai reference" title="Trainer's example from Civitai">`
          : (rec.civitai_preview_url
              ? `<img class="sc-calib-ref" src="${rec.civitai_preview_url}" alt="Civitai reference" title="Trainer's example from Civitai" loading="lazy" onerror="this.style.display='none'">`
              : '');
      el.innerHTML = `
        <div class="sc-calib-thumb${refImg ? ' with-ref' : ''}">
          ${ok ? `<img src="data:image/png;base64,${rec.image_b64}" alt="${rec.lora_name}">` : `<div class="err">${(rec.error || 'no sample').toString()}</div>`}
          ${refImg}
          ${scoreChip(rec)}
        </div>
        <div class="sc-calib-name">${rec.lora_name}${nsfwTag}${extraBadges(rec)}</div>
        <div class="sc-calib-chips">${chipsFor(rec)}</div>
        ${trigs ? `<div class="sc-calib-trig">triggers: ${trigs}</div>` : ''}
        <div class="sc-calib-row">
          <button class="sc-calib-confirm-btn" ${!ok ? 'disabled' : ''}>\u2713 Confirm</button>
          <button class="sc-calib-custom-btn" title="Open manual shootout for this group">\u2699</button>
          ${civ ? `<span style="align-self:center">${civ}</span>` : ''}
        </div>
      `;
      el.querySelector('.sc-calib-confirm-btn').addEventListener('click', () => doConfirm(rec, el));
      el.querySelector('.sc-calib-custom-btn').addEventListener('click', () => {
        selectTab('compare');
      });
      if (state.confirmed.has(rec.lora_name)) markConfirmed(el, false);
      else if (state.autoConfirmedNames.has(rec.lora_name)) markConfirmed(el, true);

      maybeAutoConfirm(rec, el);
    }

    function markConfirmed(el, auto) {
      el.classList.add('confirmed');
      if (auto) el.classList.add('auto-confirmed');
      const b = el.querySelector('.sc-calib-confirm-btn');
      if (b) { b.disabled = true; b.textContent = auto ? '✓ Auto-confirmed' : '✓ Confirmed'; }
    }

    async function doConfirm(rec, el, auto) {
      const btn = el.querySelector('.sc-calib-confirm-btn');
      if (btn) { btn.disabled = true; btn.textContent = auto ? 'Auto…' : 'Confirming…'; }
      try {
        await api('/api/spellcaster/lora/calibrate/confirm', {
          method: 'POST',
          body: JSON.stringify({
            lora_name: rec.lora_name,
            strength: rec.strength, sampler: rec.sampler || undefined,
            cfg: rec.cfg, subject_key: rec.subject || undefined,
            trigger_words: rec.trigger_words || undefined,
            base_model: (rec.knowledge && rec.knowledge.base_model) || rec.arch || undefined,
            sha256: (rec.knowledge && rec.knowledge.sha256) || undefined,
            nsfw: !!rec.nsfw,
            source: auto ? 'auto_confirm_llm' : 'user_confirm',
            extra: auto && typeof rec.score === 'number'
                    ? { score: rec.score, score_reason: rec.score_reason }
                    : undefined,
          }),
        });
        if (auto) state.autoConfirmedNames.add(rec.lora_name);
        else state.confirmed.add(rec.lora_name);
        markConfirmed(el, auto);
      } catch (e) {
        if (btn) { btn.disabled = false; btn.textContent = '✓ Confirm'; btn.title = String(e); }
      }
    }

    function maybeAutoConfirm(rec, el) {
      if (!scoreChk.checked) return;
      if (state.confirmed.has(rec.lora_name)) return;
      if (state.autoConfirmedNames.has(rec.lora_name)) return;
      if (typeof rec.score !== 'number') return;
      const thresh = parseFloat(threshInp.value || '7.5');
      if (rec.score >= thresh && rec.ok) {
        doConfirm(rec, el, /*auto=*/true);
      }
    }

    async function confirmAllVisible() {
      const cards = [...groupsEl.querySelectorAll('.sc-calib-card:not(.confirmed):not(.failed)')];
      confirmAllBtn.disabled = true;
      confirmAllBtn.textContent = `Confirming ${cards.length}…`;
      for (const c of cards) {
        const b = c.querySelector('.sc-calib-confirm-btn');
        if (b && !b.disabled) b.click();
        await new Promise((r) => setTimeout(r, 60));
      }
      confirmAllBtn.textContent = 'Confirm all visible';
      confirmAllBtn.disabled = false;
    }
    confirmAllBtn.addEventListener('click', confirmAllVisible);

    function renderSkipped(list) {
      if (!list || !list.length) { skippedEl.style.display = 'none'; return; }
      const byReason = {};
      for (const sk of list) {
        const r = sk.reason || 'skipped';
        (byReason[r] ||= []).push(sk);
      }
      const blocks = Object.entries(byReason).map(([reason, entries]) => {
        const names = entries.map(e => `<li>${e.lora_name}</li>`).join('');
        return `<div style="margin-bottom:6px"><strong style="color:#e8590c">${reason}</strong> — ${entries.length} LoRA${entries.length === 1 ? '' : 's'}<ul>${names}</ul></div>`;
      }).join('');
      skippedEl.innerHTML = `
        <div class="sc-calib-skipped-head">
          <span>${list.length} LoRA${list.length === 1 ? '' : 's'} skipped — click for details</span>
          <span class="sc-calib-chev">▸</span>
        </div>
        <div class="sc-calib-skipped-list">${blocks}</div>
      `;
      skippedEl.style.display = 'block';
      skippedEl.querySelector('.sc-calib-skipped-head').addEventListener('click', () => {
        skippedEl.classList.toggle('open');
      });
    }

    async function startJob() {
      startBtn.disabled = true; startBtn.textContent = 'Starting…';
      groupsEl.innerHTML = ''; skippedEl.style.display = 'none';
      resumeEl.style.display = 'none';
      state.samples = [];
      state.confirmed.clear();
      state.autoConfirmedNames.clear();
      const payload = {
        subset: 'unconfirmed',
        use_network: networkChk.checked,
        score_with_llm: scoreChk.checked,
        preflight: preflightChk.checked,
      };
      if (stabilityChk.checked) payload.stability_seeds = 3;
      if (sweepChk.checked) payload.sweep_strengths = [0.4, 0.7, 1.0];
      try {
        const resp = await api('/api/spellcaster/lora/calibrate/auto/start', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        state.jobId = resp.job_id;
        setStatus(`rendering 0/${resp.total}…`);
        setProgress(0, resp.total);
        cancelBtn.style.display = '';
        cancelBtn.disabled = false;
        cancelBtn.textContent = '⏹ Cancel';
        pollLoop();
      } catch (e) {
        setStatus('start failed: ' + e);
        startBtn.disabled = false; startBtn.textContent = 'Start';
      }
    }
    startBtn.addEventListener('click', startJob);

    async function doCancel() {
      if (!state.jobId) return;
      cancelBtn.disabled = true; cancelBtn.textContent = 'Cancelling…';
      try {
        const r = await api(
          '/api/spellcaster/lora/calibrate/auto/cancel?job=' + encodeURIComponent(state.jobId),
          { method: 'POST', body: '{}' }
        );
        const warn = (r.comfy && r.comfy.errors && r.comfy.errors.length)
          ? ' (ComfyUI: ' + r.comfy.errors.join(', ') + ')' : '';
        setStatus('cancel requested' + warn);
      } catch (e) {
        setStatus('cancel failed: ' + e);
        cancelBtn.disabled = false; cancelBtn.textContent = '⏹ Cancel';
      }
    }
    cancelBtn.addEventListener('click', doCancel);

    async function pollLoop() {
      state.polling = true;
      while (state.polling) {
        await new Promise((r) => setTimeout(r, 2000));
        if (!state.polling) break;
        let s;
        try { s = await api('/api/spellcaster/lora/calibrate/auto/status?job=' + encodeURIComponent(state.jobId)); }
        catch (e) { setStatus('poll error: ' + e); continue; }
        setStatus(`${s.done}/${s.total}${s.current ? ' — ' + s.current.split(/[/\\]/).pop() : ''}`);
        setProgress(s.done, s.total);
        const rendered = state.samples.length;
        for (let i = rendered; i < (s.samples || []).length; i++) {
          renderCard(s.samples[i]);
          state.samples.push(s.samples[i]);
        }
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
          updateTabCounts();
          // Refresh group membership so the compare chip count is live.
          safeApi('/api/spellcaster/lora/groups').then((g) => {
            if (g) { state.groupsData = g; updateTabCounts(); }
          });
        }
      }
    }

    async function maybeShowResumeBanner() {
      const r = await safeApi('/api/spellcaster/lora/calibrate/resumable');
      const jobs = (r && r.jobs) || [];
      if (!jobs.length) { resumeEl.style.display = 'none'; return; }
      const latest = jobs[0];     // newest first per backend sort
      const age = latest.finished_at
        ? Math.round((Date.now() / 1000 - latest.finished_at) / 60)
        : null;
      const ageTxt = age != null
        ? (age < 60 ? `${age} min ago` : `${Math.round(age / 60)} h ago`)
        : 'a previous session';
      resumeEl.innerHTML = `
        <div class="msg">
          ⏸ Previous run cut short at <strong>${latest.done ?? 0}/${latest.total ?? '?'}</strong>
          ${ageTxt}. Click Start to pick up where you left off —
          confirmed LoRAs are skipped automatically.
        </div>
        <button class="sc-calib-btn-secondary sc-calib-dismiss-resume">Dismiss</button>
      `;
      resumeEl.style.display = 'flex';
      resumeEl.querySelector('.sc-calib-dismiss-resume').addEventListener('click', async () => {
        await safeApi('/api/spellcaster/lora/calibrate/resumable/clear',
                      { method: 'POST', body: '{}' });
        resumeEl.style.display = 'none';
      });
    }

    // Initial setup when the tab opens: show summary or an empty hint.
    (async () => {
      const sum = state.summary || await safeApi('/api/spellcaster/lora/calibrate/summary');
      if (sum) state.summary = sum;
      const total = (sum && sum.registry_total) || 0;
      const confirmed = (sum && sum.registry_confirmed) || 0;
      const pending = (sum && sum.registry_unconfirmed) || 0;
      setStatus(`${pending} unconfirmed · ${confirmed}/${total} done`);
      if (pending === 0) {
        groupsEl.innerHTML = '<div class="sc-calib-empty">Every LoRA is confirmed. Nothing to calibrate.</div>';
        startBtn.disabled = true;
      }
      maybeShowResumeBanner();
    })();
  }

  // ── COMPARE tab ───────────────────────────────────────────────────────
  function renderCompareTab(body) {
    body.innerHTML = `
      <div style="margin-bottom:14px;color:#8ea0bf;font-size:13px">
        Groups with 2+ candidates — use shootouts to render them at
        identical params and pick a winner. Single-candidate groups
        land directly in the Confirm tab.
      </div>
      <div class="sc-calib-compare-list"></div>
    `;
    const listEl = body.querySelector('.sc-calib-compare-list');
    (async () => {
      const groups = state.groupsData
        || await safeApi('/api/spellcaster/lora/groups');
      if (groups) state.groupsData = groups;
      const pending = (groups && groups.pending) || [];
      if (!pending.length) {
        listEl.innerHTML = '<div class="sc-calib-empty">No pending comparisons — every group has either a winner or a single candidate.</div>';
        return;
      }
      pending.forEach((g) => {
        const row = document.createElement('div');
        row.className = 'sc-calib-compare-row';
        row.innerHTML = `
          <div>
            <div class="sc-calib-compare-row-title">${g.purpose_group.replace(/_/g, ' ')}</div>
            <div class="sc-calib-compare-row-meta">${g.arch} — ${g.count} candidates</div>
          </div>
          <button class="sc-calib-btn-primary">Run shootout</button>
        `;
        row.querySelector('button').addEventListener('click', () => {
          // Hand off to the legacy shootouts modal; its own modal will
          // layer on top of ours. Close ours so the user has one
          // modal at a time.
          const s = window.SpellcasterShootout;
          if (s && s.open) s.open();
          if (state.activeOverlay) state.activeOverlay.remove();
          state.polling = false;
          state.activeOverlay = null;
        });
        listEl.appendChild(row);
      });
    })();
  }

  // ── STATS tab ─────────────────────────────────────────────────────────
  function renderStatsTab(body) {
    const sum = state.summary || {};
    const scorer = state.scorer || {};
    body.innerHTML = `
      <div class="sc-calib-preflight-panel" style="background:#141c2b;border:1px solid #1f2a3d;border-radius:8px;padding:14px;margin-bottom:12px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <div class="sc-preflight-stats-dot" style="width:14px;height:14px;border-radius:50%;background:#6c757d"></div>
          <div style="font-weight:600;color:#e8e6f5;flex:1">
            System preflight <span class="sc-preflight-state-label" style="color:#8ea0bf;font-weight:400"></span>
          </div>
          <button class="sc-calib-btn-secondary sc-preflight-rerun">Re-run preflight</button>
        </div>
        <div class="sc-preflight-headline" style="font-size:12px;color:#8ea0bf;margin-bottom:10px"></div>
        <div class="sc-preflight-details" style="font-size:12px"></div>
      </div>
      <div class="sc-calib-stats-grid">
        <div class="sc-calib-stat">
          <div class="sc-calib-stat-num">${sum.registry_total ?? '–'}</div>
          <div class="sc-calib-stat-label">LoRAs in registry</div>
        </div>
        <div class="sc-calib-stat">
          <div class="sc-calib-stat-num">${sum.registry_confirmed ?? '–'}</div>
          <div class="sc-calib-stat-label">confirmed</div>
        </div>
        <div class="sc-calib-stat">
          <div class="sc-calib-stat-num">${sum.registry_unconfirmed ?? '–'}</div>
          <div class="sc-calib-stat-label">pending confirmation</div>
        </div>
        <div class="sc-calib-stat">
          <div class="sc-calib-stat-num">${sum.sfw_count ?? '–'}</div>
          <div class="sc-calib-stat-label">SFW recipes stored</div>
        </div>
        <div class="sc-calib-stat">
          <div class="sc-calib-stat-num">${sum.nsfw_count ?? '–'}</div>
          <div class="sc-calib-stat-label">NSFW recipes stored</div>
        </div>
        <div class="sc-calib-stat">
          <div class="sc-calib-stat-num">${sum.confirmed_count ?? '–'}</div>
          <div class="sc-calib-stat-label">user-confirmed in store</div>
        </div>
      </div>
      <div style="background:#141c2b;border:1px solid #1f2a3d;border-radius:8px;padding:14px;margin-bottom:12px">
        <div style="font-weight:600;color:#e8e6f5;margin-bottom:6px">Vision scorer</div>
        <div style="font-size:12px;color:#8ea0bf">
          ${scorer.ok
            ? `<span style="color:#20c997">● online</span> — model <code>${scorer.model}</code> is installed and ready for auto-confirm.`
            : `<span style="color:#e03131">● offline</span> — ${scorer.reason || 'scorer probe failed'}. Auto-confirm is disabled.`}
        </div>
      </div>
      <div style="font-size:12px;color:#8ea0bf">
        SFW store: <code>${sum.sfw_path || '—'}</code><br>
        NSFW store: <code>${sum.nsfw_path || '—'}</code>
      </div>
    `;

    const panel = body.querySelector('.sc-calib-preflight-panel');
    const dotEl = panel.querySelector('.sc-preflight-stats-dot');
    const label = panel.querySelector('.sc-preflight-state-label');
    const headline = panel.querySelector('.sc-preflight-headline');
    const details = panel.querySelector('.sc-preflight-details');
    const rerunBtn = panel.querySelector('.sc-preflight-rerun');

    function paint(p) {
      if (!p) return;
      const colour = {
        green: '#20c997', yellow: '#ffc107',
        red: '#e03131', unknown: '#6c757d',
      }[p.overall] || '#6c757d';
      dotEl.style.background = colour;
      label.textContent = p.overall ? '— ' + p.overall : '';
      headline.textContent = p.headline || '';
      const fs = p.faceswap || {};
      const sc = p.scorer || {};
      const canaries = (p.canaries || []).map(c =>
        `<li style="list-style:none;padding:2px 0;font-family:Consolas,monospace">
          <span style="color:${c.ok ? '#20c997' : '#e03131'}">${c.ok ? '✓' : '✗'}</span>
          ${c.arch}${c.ok ? '' : ' — ' + (c.error || 'failed')}
        </li>`
      ).join('');
      const canaryAge = p.canary_ran_at
        ? Math.round((Date.now()/1000 - p.canary_ran_at) / 60) + ' min ago'
        : 'never run';
      details.innerHTML = `
        <div style="color:#d9e1ed;margin-bottom:4px">
          ComfyUI: <span style="color:${p.comfy_reachable ? '#20c997' : '#e03131'}">
            ${p.comfy_reachable ? 'reachable' : (p.comfy_error || 'unreachable')}</span>
        </div>
        <div style="color:#d9e1ed;margin-bottom:4px">
          Face-swap state: <code>${fs.state || '?'}</code>
          ${fs.state_reason ? ' — <span style="color:#8ea0bf">' + fs.state_reason + '</span>' : ''}
        </div>
        <div style="color:#d9e1ed;margin-bottom:4px">
          Vision scorer: ${sc.ok ? '<span style="color:#20c997">online</span>' : '<span style="color:#e03131">offline</span>'}
          ${sc.reason ? ' — <span style="color:#8ea0bf">' + sc.reason + '</span>' : ''}
        </div>
        <div style="color:#d9e1ed;margin-top:8px">
          Per-arch canaries (${canaryAge}):
        </div>
        <ul style="padding:2px 0 0 10px;margin:0">${canaries || '<li style="list-style:none;color:#8ea0bf;font-style:italic">no preflight run yet — click "Re-run preflight" to start</li>'}</ul>
      `;
      if (p.run_job && p.run_job.running) {
        rerunBtn.disabled = true;
        rerunBtn.textContent = 'Running ' + (p.run_job.progress || '…');
      } else {
        rerunBtn.disabled = false;
        rerunBtn.textContent = 'Re-run preflight';
      }
    }

    async function refresh() {
      try {
        const r = await fetch('/api/spellcaster/preflight/status');
        if (!r.ok) return;
        const p = await r.json();
        state.preflight = p;
        paint(p);
      } catch {}
    }

    rerunBtn.addEventListener('click', async () => {
      rerunBtn.disabled = true; rerunBtn.textContent = 'Starting…';
      try {
        await fetch('/api/spellcaster/preflight/run', { method: 'POST', body: '{}' });
      } catch {}
      // Poll every 2s until job completes, then do one more refresh
      const poll = setInterval(async () => {
        await refresh();
        const job = (state.preflight && state.preflight.run_job) || {};
        if (!job.running) {
          clearInterval(poll);
          refreshPreflightDot();
        }
      }, 2000);
    });

    paint(state.preflight);
    refresh();
  }

  // ── Boot ──────────────────────────────────────────────────────────────
  function boot() { refreshButton(); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }
  setInterval(refreshButton, 60000);

  window.SpellcasterCalibration = { open: openModal, refresh: refreshButton };
})();
