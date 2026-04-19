/*  Spellcaster LLM-free setup wizard.
 *
 *  The chat-driven Spellcaster needs an LLM to hold conversation. On
 *  a fresh install there IS no LLM yet (`prompt_enhance` is the first
 *  thing the user needs to install), so this module takes over the
 *  Guild UI with a plain-form, clickable flow that walks through the
 *  same 5 beats the LLM-driven scaffold uses:
 *
 *    Beat 1 — Network survey        (forms)
 *    Beat 2 — Intent picker         (chips)
 *    Beat 3 — Plan preview          (tier table + narrative)
 *    Beat 4 — Install loop          (progress bars per feature)
 *    Beat 5 — Hand-off              (reveals the chat once LLM is up)
 *
 *  All backend calls are the same /api/spellcaster/* endpoints the
 *  scaffold uses — zero duplicated logic. The moment `llm_available`
 *  flips true (after prompt_enhance lands), the overlay fades out
 *  and the normal chat UI is revealed.
 *
 *  Triggered automatically when:
 *    - GET /api/spellcaster/state returns system.llm_available === false
 *    - AND setup_mode is active OR the Spellcaster wizard is selected
 */
(function () {
  'use strict';
  if (window.SpellcasterSetupWizard) return;

  const ENDPOINT = {
    state:      '/api/spellcaster/state',
    survey:     '/api/spellcaster/network/survey',
    declare:    '/api/spellcaster/network/declare',
    refresh:    '/api/spellcaster/network/refresh',
    plan:       '/api/spellcaster/install/plan',
    quote:      '/api/spellcaster/quote',
    featInst:   '/api/spellcaster/feature/install',
    antennaTest:'/api/spellcaster/antenna/test',
    cueState:   '/api/spellcaster/cue',
  };

  const USAGE_BUNDLES = {
    portraits:   ['img2img', 'face_swap_reactor', 'face_restore', 'upscale', 'segment'],
    photo_edit:  ['klein_flux2', 'flux_kontext', 'iclight', 'segment', 'lama_remove', 'rembg'],
    fantasy:     ['img2img', 'klein_flux2', 'upscale', 'controlnet', 'segment'],
    anime:       ['img2img', 'upscale', 'face_swap_reactor', 'segment'],
    video:       ['img2img', 'wan_i2v', 'upscale', 'face_swap_reactor'],
    restoration: ['upscale', 'supir', 'face_restore', 'lama_remove'],
    everything:  ['img2img', 'klein_flux2', 'flux_kontext', 'face_swap_reactor',
                  'face_restore', 'upscale', 'segment', 'controlnet', 'iclight',
                  'lama_remove', 'rembg', 'wan_i2v'],
  };

  const BUNDLE_LABELS = {
    portraits:   '👤 Portraits',
    photo_edit:  '✏️ Photo editing',
    fantasy:     '🐉 Fantasy art',
    anime:       '🌸 Anime',
    video:       '🎬 Video',
    restoration: '🖼 Restoration',
    everything:  '✨ Everything',
  };

  // ── Style injection ───────────────────────────────────────────────
  const STYLE_ID = 'sc-setup-style';
  if (!document.getElementById(STYLE_ID)) {
    const st = document.createElement('style');
    st.id = STYLE_ID;
    st.textContent = `
      #sc-setup-overlay {
        position: fixed; inset: 0; z-index: 900;
        background: radial-gradient(ellipse at top, #1a1237 0%, #05030f 70%);
        color: #e8e6f5; overflow: auto;
        display: flex; flex-direction: column; align-items: center;
        padding: 36px 20px 60px;
        font-family: -apple-system, system-ui, sans-serif;
      }
      #sc-setup-overlay.fade-out { opacity: 0; transition: opacity .6s ease;
                                    pointer-events: none; }
      .sc-setup-header {
        text-align: center; max-width: 680px; margin-bottom: 24px;
      }
      .sc-setup-header h1 {
        font-size: 28px; margin: 0 0 8px;
        background: linear-gradient(135deg, #c084fc, #ffd700);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text;
      }
      .sc-setup-header p { color: #a89bcc; margin: 0; font-size: 14px; }
      .sc-setup-steps {
        display: flex; gap: 10px; margin: 8px 0 24px;
      }
      .sc-setup-step {
        width: 34px; height: 34px; border-radius: 50%;
        background: #12101d; color: #a89bcc;
        border: 2px solid #2a2440; display: flex;
        align-items: center; justify-content: center;
        font-size: 13px; font-weight: 600;
      }
      .sc-setup-step.active { background: #6a1b9a; color: white;
                              border-color: #ffd700; }
      .sc-setup-step.done { background: #4caf50; color: white;
                            border-color: #4caf50; }
      .sc-setup-card {
        background: #12101d; border: 1px solid #2a2440; border-radius: 14px;
        width: 92%; max-width: 820px; padding: 24px 28px;
        margin-bottom: 16px;
      }
      .sc-setup-card h2 { margin: 0 0 14px; font-size: 20px; color: #ffd700; }
      .sc-setup-card p  { color: #c4b8e3; font-size: 14px; line-height: 1.5; }
      .sc-service-row {
        display: grid; grid-template-columns: 1fr auto auto;
        gap: 10px; align-items: center;
        padding: 12px 0; border-bottom: 1px solid #1a1730;
      }
      .sc-service-row:last-child { border-bottom: none; }
      .sc-service-name { font-weight: 600; color: #e8e6f5; }
      .sc-service-desc { grid-column: 1 / -1;
                          font-size: 11px; color: #8a7eaf;
                          margin-top: 2px; }
      .sc-placement-select {
        background: #1a1730; color: #e8e6f5;
        border: 1px solid #2a2440; border-radius: 6px;
        padding: 6px 10px; font-size: 13px;
      }
      .sc-host-input {
        background: #1a1730; color: #e8e6f5;
        border: 1px solid #2a2440; border-radius: 6px;
        padding: 6px 10px; font-size: 13px; width: 170px;
      }
      .sc-host-input.hidden { display: none; }
      .sc-probe-badge {
        font-size: 11px; padding: 3px 10px; border-radius: 10px;
        font-weight: 600;
      }
      .sc-probe-badge.ok       { background: #1b5e20; color: #b9f6ca; }
      .sc-probe-badge.pending  { background: #2a2440; color: #a89bcc; }
      .sc-probe-badge.fail     { background: #b71c1c; color: #ffcdd2; }
      .sc-chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 6px; }
      .sc-chip {
        background: #1a1730; color: #c4b8e3;
        border: 1px solid #2a2440; border-radius: 18px;
        padding: 8px 14px; font-size: 13px; cursor: pointer;
      }
      .sc-chip:hover { border-color: #6a1b9a; }
      .sc-chip.selected {
        background: linear-gradient(135deg, #6a1b9a, #9c27b0);
        color: white; border-color: #ffd700;
      }
      .sc-btn-row {
        display: flex; justify-content: space-between; margin-top: 20px;
      }
      .sc-btn {
        background: #1a1730; color: #c4b8e3;
        border: 1px solid #2a2440; border-radius: 18px;
        padding: 9px 20px; font-size: 14px; font-weight: 600;
        cursor: pointer;
      }
      .sc-btn:hover { border-color: #6a1b9a; color: #e8e6f5; }
      .sc-btn.primary {
        background: linear-gradient(135deg, #6a1b9a, #ffd700);
        color: white; border-color: transparent;
      }
      .sc-btn.primary:hover { filter: brightness(1.1); }
      .sc-btn:disabled { opacity: 0.5; cursor: default; }
      .sc-plan-table { width: 100%; border-collapse: collapse; margin-top: 12px; }
      .sc-plan-table th, .sc-plan-table td {
        padding: 8px 10px; text-align: left; font-size: 13px;
        border-bottom: 1px solid #1a1730;
      }
      .sc-plan-table th { color: #8a7eaf; font-weight: 600; font-size: 11px;
                           text-transform: uppercase; letter-spacing: 0.5px; }
      .sc-plan-table tr:last-child td { border-bottom: none; }
      .sc-tier-badge {
        display: inline-block; padding: 2px 8px; border-radius: 8px;
        font-size: 10px; font-weight: 700; text-transform: uppercase;
      }
      .sc-tier-0 { background: #ffd700; color: #12101d; }
      .sc-tier-1 { background: #66bb6a; color: #12101d; }
      .sc-tier-2 { background: #ab47bc; color: white; }
      .sc-tier-3 { background: #42a5f5; color: white; }
      .sc-tier-4 { background: #7e57c2; color: white; }
      .sc-tier-5 { background: #ef5350; color: white; }
      .sc-quote {
        background: #1a1730; border-radius: 10px; padding: 14px 18px;
        margin-top: 16px; color: #ffd700; font-size: 15px;
      }
      .sc-quote-stat { display: inline-block; margin-right: 18px; }
      .sc-narrative { font-size: 13px; color: #c4b8e3; padding: 0; margin: 10px 0 0; }
      .sc-narrative li { margin-bottom: 4px; }
      .sc-install-row {
        display: grid; grid-template-columns: 28px 1fr auto;
        gap: 10px; align-items: center;
        padding: 12px 0; border-bottom: 1px solid #1a1730;
      }
      .sc-install-icon { font-size: 18px; }
      .sc-install-name { font-weight: 600; }
      .sc-install-status { font-size: 12px; color: #8a7eaf; }
      .sc-install-status.running { color: #ffd700; }
      .sc-install-status.done    { color: #81c784; }
      .sc-install-status.failed  { color: #ef5350; }
    `;
    document.head.appendChild(st);
  }

  // ── State ─────────────────────────────────────────────────────────
  const S = {
    step: 0,                   // 0-4
    survey: {},                // from GET /network/survey
    catalog: [],
    bundle: '',                // selected USAGE_BUNDLE key
    features: [],              // final feature list
    plan: null,                // from /install/plan
    quote: null,               // from /quote
    installIndex: 0,
    installResults: [],
  };

  let el = null;               // overlay root

  // ── API helpers ───────────────────────────────────────────────────
  async function api(path, opts) {
    const r = await fetch(path, opts);
    const txt = await r.text();
    let body; try { body = JSON.parse(txt); } catch { body = { raw: txt }; }
    if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
    return body;
  }

  // ── Rendering framework (tiny) ────────────────────────────────────
  function mount(innerHTML) {
    if (!el) {
      el = document.createElement('div');
      el.id = 'sc-setup-overlay';
      document.body.appendChild(el);
    }
    const stepNames = ['Network', 'Intent', 'Plan', 'Install', 'Done'];
    el.innerHTML = `
      <div class="sc-setup-header">
        <h1>✦ Spellcaster ✦</h1>
        <p>Let's get your stack installed. You'll answer a few questions;
           I'll handle the rest.</p>
      </div>
      <div class="sc-setup-steps">
        ${stepNames.map((name, i) => `
          <div class="sc-setup-step ${
            i === S.step ? 'active' : (i < S.step ? 'done' : '')
          }" title="${name}">${i + 1}</div>`).join('')}
      </div>
      ${innerHTML}
    `;
  }

  // ── Beat 1: Network survey ────────────────────────────────────────
  async function renderNetwork() {
    mount(`<div class="sc-setup-card"><p>Loading service catalog…</p></div>`);
    try {
      const data = await api(ENDPOINT.survey);
      S.catalog = data.catalog || [];
      S.survey  = data.survey  || {};
    } catch (e) {
      mount(`<div class="sc-setup-card">
        <h2>Network survey failed</h2>
        <p>${e.message}</p>
        <div class="sc-btn-row"><span></span>
          <button class="sc-btn primary" onclick="SpellcasterSetupWizard.step1()">Retry</button>
        </div>
      </div>`);
      return;
    }
    const rows = S.catalog.map(svc => {
      const loc = S.survey[svc.key] || {placement: 'unknown'};
      const isRemote = loc.placement === 'remote';
      const badge = loc.verified ? 'ok'
        : (loc.last_probe_error ? 'fail' : 'pending');
      const badgeText = loc.verified ? '✓ verified'
        : (loc.last_probe_error ? '✗ ' + (loc.last_probe_error.length > 24
            ? loc.last_probe_error.slice(0, 22) + '…'
            : loc.last_probe_error) : '…');
      return `
        <div class="sc-service-row" data-key="${svc.key}">
          <div>
            <div class="sc-service-name">${svc.label}</div>
            <div class="sc-service-desc">${svc.description}</div>
          </div>
          <div>
            <select class="sc-placement-select" data-field="placement">
              <option value="local"         ${loc.placement==='local'?'selected':''}>This machine</option>
              <option value="remote"        ${isRemote?'selected':''}>On my LAN</option>
              <option value="not_installed" ${loc.placement==='not_installed'?'selected':''}>Not installed</option>
              <option value="skip"          ${loc.placement==='skip'?'selected':''}>Skip</option>
              <option value="unknown"       ${loc.placement==='unknown'?'selected':''}>Not sure</option>
            </select>
            <input class="sc-host-input ${isRemote?'':'hidden'}"
                   placeholder="host or IP" value="${loc.host||''}"
                   data-field="host">
          </div>
          <span class="sc-probe-badge ${badge}">${badgeText}</span>
        </div>`;
    }).join('');
    mount(`
      <div class="sc-setup-card">
        <h2>1. Where does each service live?</h2>
        <p>Before downloading anything, I need to know if ComfyUI, SillyTavern,
           and friends run on this machine or another box on your network.
           Anything "On my LAN" needs a Spellcaster Antenna running there —
           I'll verify each as you declare it.</p>
        ${rows}
        <div class="sc-btn-row">
          <span></span>
          <button class="sc-btn primary" id="sc-next-1">Continue →</button>
        </div>
      </div>
    `);
    // Wire rows
    el.querySelectorAll('.sc-service-row').forEach(row => {
      const key = row.dataset.key;
      const sel = row.querySelector('[data-field="placement"]');
      const host = row.querySelector('[data-field="host"]');
      sel.addEventListener('change', async () => {
        host.classList.toggle('hidden', sel.value !== 'remote');
        if (sel.value !== 'remote') {
          await declare(key, sel.value, '');
        }
      });
      host.addEventListener('change', async () => {
        await declare(key, 'remote', host.value.trim());
      });
    });
    el.querySelector('#sc-next-1').addEventListener('click', () => {
      S.step = 1; renderIntent();
    });
  }

  async function declare(key, placement, host) {
    try {
      const r = await api(ENDPOINT.declare, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key, placement, host}),
      });
      S.survey[key] = r.service || {placement, host};
      renderNetwork();       // re-render to update badge
    } catch (e) {
      console.error('declare failed', e);
    }
  }

  // ── Beat 2: Intent ────────────────────────────────────────────────
  function renderIntent() {
    const chips = Object.entries(BUNDLE_LABELS).map(([key, label]) => `
      <div class="sc-chip ${S.bundle===key?'selected':''}" data-bundle="${key}">
        ${label}
      </div>`).join('');
    mount(`
      <div class="sc-setup-card">
        <h2>2. What do you want to do?</h2>
        <p>Pick the closest match. I'll pre-select a sensible feature set —
           you can tweak it in the next step.</p>
        <div class="sc-chip-row">${chips}</div>
        <div class="sc-btn-row">
          <button class="sc-btn" id="sc-back-2">← Back</button>
          <button class="sc-btn primary" id="sc-next-2" ${S.bundle?'':'disabled'}>Continue →</button>
        </div>
      </div>
    `);
    el.querySelectorAll('.sc-chip').forEach(c => {
      c.addEventListener('click', () => {
        S.bundle = c.dataset.bundle;
        S.features = USAGE_BUNDLES[S.bundle].slice();
        renderIntent();
      });
    });
    el.querySelector('#sc-back-2').addEventListener('click', () => {
      S.step = 0; renderNetwork();
    });
    el.querySelector('#sc-next-2').addEventListener('click', () => {
      if (!S.bundle) return;
      S.step = 2; renderPlan();
    });
  }

  // ── Beat 3: Plan + quote ──────────────────────────────────────────
  async function renderPlan() {
    mount(`<div class="sc-setup-card"><p>Building your plan…</p></div>`);
    let plan, quote;
    try {
      plan  = await api(ENDPOINT.plan,  {method:'POST', headers:{'Content-Type':'application/json'},
                                          body: JSON.stringify({features: S.features})});
      quote = await api(ENDPOINT.quote, {method:'POST', headers:{'Content-Type':'application/json'},
                                          body: JSON.stringify({features: S.features})});
    } catch (e) {
      mount(`<div class="sc-setup-card"><h2>Couldn't build plan</h2>
        <p>${e.message}</p>
        <div class="sc-btn-row"><button class="sc-btn" onclick="SpellcasterSetupWizard.step2()">← Back</button>
          <button class="sc-btn primary" onclick="SpellcasterSetupWizard.step3()">Retry</button></div></div>`);
      return;
    }
    S.plan = plan; S.quote = quote;
    const rows = (plan.steps || []).map(s => `
      <tr>
        <td><span class="sc-tier-badge sc-tier-${s.tier}">T${s.tier}</span></td>
        <td><strong>${s.label}</strong><br><span style="color:#8a7eaf;font-size:11px">${s.why}</span></td>
        <td>${s.demo_gen_prompt ? '🎨' : ''}</td>
      </tr>`).join('');
    const narr = (plan.narrative || []).map(n => `<li>${n}</li>`).join('');
    mount(`
      <div class="sc-setup-card">
        <h2>3. Here's the plan</h2>
        <p>Ordered so you see results as fast as possible. Tier 0 first
           (that's the LLM — gets me talking back richer); then small &
           proven, then headline quality, then utilities. Video last.</p>
        <div class="sc-quote">
          <span class="sc-quote-stat">📦 <strong>${quote.size_gb} GB</strong> to download</span>
          <span class="sc-quote-stat">🔓 <strong>${quote.method_count} tools</strong> unlocked</span>
          <span class="sc-quote-stat">🧩 ${quote.models} models</span>
        </div>
        <ul class="sc-narrative">${narr}</ul>
        <table class="sc-plan-table">
          <thead><tr><th>Tier</th><th>Feature</th><th>Demo</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="sc-btn-row">
          <button class="sc-btn" id="sc-back-3">← Back</button>
          <button class="sc-btn primary" id="sc-next-3">Start installing →</button>
        </div>
      </div>
    `);
    el.querySelector('#sc-back-3').addEventListener('click', () => {
      S.step = 1; renderIntent();
    });
    el.querySelector('#sc-next-3').addEventListener('click', () => {
      S.step = 3; S.installIndex = 0; S.installResults = []; renderInstall();
    });
  }

  // ── Beat 4: Install loop ──────────────────────────────────────────
  async function renderInstall() {
    const steps = S.plan.steps || [];
    const rows = steps.map((s, i) => {
      const result = S.installResults[i] || {};
      const statusClass = i < S.installIndex ? (result.ok ? 'done' : 'failed')
        : (i === S.installIndex ? 'running' : '');
      const icon = i < S.installIndex ? (result.ok ? '✓' : '✗')
        : (i === S.installIndex ? '⟳' : '◌');
      const statusText = i < S.installIndex
        ? (result.ok ? 'installed' : (result.error || 'failed'))
        : (i === S.installIndex ? s.demo_cue || 'installing…' : 'queued');
      return `
        <div class="sc-install-row">
          <div class="sc-install-icon">${icon}</div>
          <div>
            <div class="sc-install-name">
              <span class="sc-tier-badge sc-tier-${s.tier}">T${s.tier}</span>
              ${s.label}
            </div>
            <div class="sc-install-status ${statusClass}">${statusText}</div>
          </div>
          <div></div>
        </div>`;
    }).join('');
    const done = S.installIndex >= steps.length;
    mount(`
      <div class="sc-setup-card">
        <h2>4. Installing</h2>
        ${rows}
        ${done ? `<div class="sc-btn-row">
          <span></span>
          <button class="sc-btn primary" id="sc-next-4">Finish →</button>
        </div>` : ''}
      </div>
    `);
    if (done) {
      el.querySelector('#sc-next-4').addEventListener('click', finish);
      return;
    }
    // Kick the next install (single item — backend serializes).
    const step = steps[S.installIndex];
    try {
      const res = await api(ENDPOINT.featInst, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({feature: step.feature}),
      });
      S.installResults[S.installIndex] = {ok: res.status === 'installed' || res.returncode === 0,
                                            error: res.error || ''};
    } catch (e) {
      S.installResults[S.installIndex] = {ok: false, error: e.message};
    }
    S.installIndex += 1;
    // After each install, re-probe LLM so we can hand off early if
    // prompt_enhance just finished landing.
    await checkLlmAndMaybeHandoff();
    renderInstall();
  }

  async function checkLlmAndMaybeHandoff() {
    try {
      const st = await api(ENDPOINT.state);
      if (st.system && st.system.llm_available) {
        // LLM is up — we could hand off mid-install. But the user
        // is watching install progress, so only hand off at the
        // very end (finish()) to avoid yanking the UI.
        S.llmUp = true;
      }
    } catch {}
  }

  // ── Beat 5: Finish + hand-off ─────────────────────────────────────
  async function finish() {
    mount(`
      <div class="sc-setup-card" style="text-align:center;">
        <h2>✨ Setup complete</h2>
        <p>The Spellcaster wizard is now ready to chat with you.
           You can always come back here to add tools, calibrate a
           model, or walk a LoRA through the shootout.</p>
        <div class="sc-btn-row" style="justify-content:center;">
          <button class="sc-btn primary" id="sc-done">Enter the Guild →</button>
        </div>
      </div>
    `);
    el.querySelector('#sc-done').addEventListener('click', () => {
      el.classList.add('fade-out');
      setTimeout(() => { if (el) el.remove(); el = null; }, 700);
    });
  }

  // ── Boot gate ─────────────────────────────────────────────────────
  async function shouldRun() {
    try {
      const st = await api(ENDPOINT.state);
      return !(st.system && st.system.llm_available);
    } catch {
      return false;        // can't reach Guild; let the main UI handle.
    }
  }

  async function maybeLaunch() {
    const run = await shouldRun();
    if (!run) return;
    S.step = 0;
    renderNetwork();
  }

  window.SpellcasterSetupWizard = {
    maybeLaunch,
    step1: renderNetwork,
    step2: renderIntent,
    step3: renderPlan,
    step4: renderInstall,
    step5: finish,
    close:  () => { if (el) { el.classList.add('fade-out');
                              setTimeout(() => { if (el) el.remove(); el = null; }, 600); } },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', maybeLaunch);
  } else {
    maybeLaunch();
  }
})();
