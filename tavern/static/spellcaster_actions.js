/*  Spellcaster <ACTION> parser + button renderer.
 *
 *  The Spellcaster onboarding wizard's scaffold system prompt (see
 *  scaffold/spellcaster_wizard.py) tells the LLM to emit action requests as:
 *
 *      <ACTION>{"type": "install_feature", "feature": "klein_flux2"}</ACTION>
 *
 *  Before this module existed, those tags rendered as raw text in the
 *  chat bubble. Now: we strip them from the displayed text and render
 *  a row of clickable buttons below the wizard's message instead. The
 *  user clicks once; the button POSTs to the matching Guild endpoint
 *  and self-updates with success / failure state. Chat keeps flowing.
 *
 *  The action → endpoint map mirrors scaffold.spellcaster_wizard.
 *  action_to_endpoint(). Keep the two in sync: any new action type
 *  added there needs a corresponding entry here or the UI will
 *  silently drop it.
 */
(function (global) {
  'use strict';

  const ACTION_RE = /<ACTION>\s*([\s\S]+?)\s*<\/ACTION>/g;

  // ── Style injection (idempotent) ──────────────────────────────────────
  const STYLE_ID = 'sc-actions-style';
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      .sc-action-row {
        display: flex; flex-wrap: wrap; gap: 8px;
        margin-top: 10px;
      }
      .sc-action-btn {
        background: linear-gradient(135deg, #6a1b9a, #9c27b0);
        color: white; border: 0; border-radius: 18px;
        padding: 8px 16px; font-size: 13px; font-weight: 600;
        cursor: pointer; white-space: nowrap;
        box-shadow: 0 2px 8px rgba(106, 27, 154, 0.35);
        transition: transform .1s, box-shadow .15s, filter .1s;
      }
      .sc-action-btn:hover:not(:disabled) {
        transform: translateY(-1px); filter: brightness(1.1);
        box-shadow: 0 4px 12px rgba(106, 27, 154, 0.5);
      }
      .sc-action-btn:disabled { cursor: default; opacity: 0.75; }
      .sc-action-btn.sc-action-btn-done {
        background: linear-gradient(135deg, #2e7d32, #66bb6a);
        box-shadow: 0 2px 8px rgba(46, 125, 50, 0.35);
      }
      .sc-action-btn.sc-action-btn-err {
        background: linear-gradient(135deg, #b71c1c, #e53935);
        box-shadow: 0 2px 8px rgba(183, 28, 28, 0.35);
      }
      .sc-action-spinner {
        display: inline-block; width: 10px; height: 10px;
        border: 2px solid rgba(255,255,255,0.4); border-top-color: white;
        border-radius: 50%; animation: sc-spin 0.8s linear infinite;
        margin-right: 6px; vertical-align: -1px;
      }
      @keyframes sc-spin { to { transform: rotate(360deg); } }
    `;
    document.head.appendChild(style);
  }

  // ── Helpers ───────────────────────────────────────────────────────────
  function prettyName(s) {
    return String(s || '').replace(/_/g, ' ').replace(/\b\w/g,
      c => c.toUpperCase());
  }

  function featureLabel(a) {
    return `Install ${prettyName(a.feature || 'feature')}`;
  }

  function summarizeList(arr) {
    if (!Array.isArray(arr) || !arr.length) return '';
    if (arr.length === 1) return prettyName(arr[0]);
    return `${prettyName(arr[0])} +${arr.length - 1}`;
  }

  // ── Action → endpoint map ────────────────────────────────────────────
  // Mirrors scaffold.spellcaster_wizard.action_to_endpoint(). Every entry:
  //   label: string|fn(action) — button text
  //   method: 'GET' | 'POST'
  //   path:   string|fn(action) — URL (GET may use a fn to build query)
  //   body:   fn(action) — body dict for POST (ignored on GET)
  //   done:   optional — text shown on success (default '\u2713 <label>')
  const ACTION_MAP = {
    install_feature: {
      label: featureLabel,
      method: 'POST', path: '/api/spellcaster/feature/install',
      body: a => ({ feature: a.feature || '' }),
    },
    uninstall_feature: {
      label: a => `Uninstall ${prettyName(a.feature || 'feature')}`,
      method: 'POST', path: '/api/spellcaster/feature/uninstall',
      body: a => ({ feature: a.feature || '' }),
    },
    quote: {
      label: a => `Estimate size: ${summarizeList(a.features)}`,
      method: 'POST', path: '/api/spellcaster/quote',
      body: a => ({ features: a.features || [] }),
    },
    install_plugin: {
      label: a => `Install ${prettyName(a.plugin || 'plugin')} plugin`,
      method: 'POST', path: '/api/spellcaster/plugin/install',
      body: a => ({ plugin: a.plugin || '' }),
    },
    uninstall_plugin: {
      label: a => `Uninstall ${prettyName(a.plugin || 'plugin')} plugin`,
      method: 'POST', path: '/api/spellcaster/plugin/uninstall',
      body: a => ({ plugin: a.plugin || '' }),
    },
    test_feature: {
      label: a => `Test ${prettyName(a.feature || 'feature')}`,
      method: 'POST', path: '/api/spellcaster/feature/test',
      body: a => ({ feature: a.feature || '' }),
    },
    start_antenna_setup: {
      label: 'Set up Antenna',
      method: 'POST', path: '/api/spellcaster/antenna/start',
      body: () => ({}),
    },
    antenna_test: {
      label: a => `Test antenna @ ${a.host || '?'}:${a.port || 8188}`,
      method: 'POST', path: '/api/spellcaster/antenna/test',
      body: a => ({ host: a.host || '', port: parseInt(a.port, 10) || 8188 }),
    },
    build_custom: {
      label: a => `Build ${prettyName(a.target || 'custom')} plugin`,
      method: 'POST', path: '/api/spellcaster/build',
      body: a => ({ target: a.target || '', features: a.features || [] }),
    },
    calibrate_lora: {
      label: a => `Calibrate LoRA: ${(a.lora || '').split(/[\/\\]/).pop()}`,
      method: 'POST', path: '/api/spellcaster/calibrate/lora',
      body: a => ({
        model: a.model || '', lora: a.lora || '',
        strengths: a.strengths || [0.3, 0.5, 0.7, 0.9],
      }),
    },
    calibrate_sampler: {
      label: a => `Sampler A/B test: ${(a.model || '').split(/[\/\\]/).pop()}`,
      method: 'POST', path: '/api/spellcaster/calibrate/sampler',
      body: a => ({
        model:      a.model || '',
        samplers:   a.samplers   || ['euler', 'dpmpp_2m'],
        schedulers: a.schedulers || ['normal', 'karras'],
      }),
    },
    calibrate_turbo: {
      label: a => `Turbo A/B test: ${(a.model || '').split(/[\/\\]/).pop()}`,
      method: 'POST', path: '/api/spellcaster/calibrate/turbo',
      body: a => ({ model: a.model || '' }),
    },
    calibrate_cfg: {
      label: a => `CFG sweep: ${(a.model || '').split(/[\/\\]/).pop()}`,
      method: 'POST', path: '/api/spellcaster/calibrate/cfg',
      body: a => ({ model: a.model || '', values: a.values || [3.0, 5.0, 7.0, 9.0] }),
    },
    calibration_save: {
      label: a => `Save settings for ${(a.model || '').split(/[\/\\]/).pop()}`,
      method: 'POST', path: '/api/spellcaster/calibration/save',
      body: a => ({ model: a.model || '', prefs: a.prefs || {} }),
    },
    lora_autosetup: {
      label: a => `Run LoRA auto-setup (${(a.loras || []).length} candidates)`,
      method: 'POST', path: '/api/spellcaster/calibrate/loras/start',
      body: a => ({ loras: a.loras || [], subset: a.subset || 'unknown' }),
    },
    lora_groups: {
      label: 'Show LoRA shootout groups',
      method: 'GET', path: () => '/api/spellcaster/lora/groups',
      body: () => ({}),
    },
    lora_shootout: {
      label: a => `Run shootout: ${a.arch || '?'} / ${prettyName(a.purpose_group || '')}`,
      method: 'POST', path: '/api/spellcaster/lora/shootout/start',
      body: a => {
        const b = {
          arch:          a.arch || '',
          purpose_group: a.purpose_group || '',
          candidates:    a.candidates || [],
          seed:          parseInt(a.seed, 10) || 12345,
        };
        if ('strength' in a) b.strength = parseFloat(a.strength);
        return b;
      },
    },
    lora_pick_preferred: {
      label: a => `Commit winner: ${(a.winner || '').split(/[\/\\]/).pop()}`,
      method: 'POST', path: '/api/spellcaster/lora/preferred',
      body: a => ({
        arch:          a.arch || '',
        purpose_group: a.purpose_group || '',
        winner:        a.winner || '',
        demote_losers: a.demote_losers !== false,
      }),
    },
    activate_model: {
      label: a => `Activate ${(a.model || '').split(/[\/\\]/).pop()}`,
      method: 'POST', path: '/api/spellcaster/activate',
      body: a => ({
        model:    a.model || '', arch: a.arch || '',
        settings: a.settings || {}, samples: a.samples || [],
        notes:    a.notes || '',
        propagate: a.propagate !== false,
      }),
    },
    deactivate_model: {
      label: a => `Deactivate ${(a.model || '').split(/[\/\\]/).pop()}`,
      method: 'POST', path: '/api/spellcaster/deactivate',
      body: a => ({ model: a.model || '' }),
    },
    scaffold_calibrate: {
      label: a => `Run scaffold calibration on ${(a.model || '').split(/[\/\\]/).pop()}`,
      method: 'POST', path: '/api/spellcaster/scaffold/calibrate',
      body: a => ({
        model: a.model || '', scenarios: a.scenarios,
        seed: parseInt(a.seed, 10) || 42,
      }),
    },
    network_survey: {
      label: 'Survey network services',
      method: 'GET', path: () => '/api/spellcaster/network/survey',
      body: () => ({}),
    },
    network_declare: {
      label: a => `Place ${prettyName(a.key || 'service')} ${a.placement || ''} ${a.host ? '@ ' + a.host : ''}`.trim(),
      method: 'POST', path: '/api/spellcaster/network/declare',
      body: a => ({
        key:          a.key || '',
        placement:    a.placement || '',
        host:         a.host || '',
        port:         parseInt(a.port, 10) || 0,
        antenna_port: parseInt(a.antenna_port, 10) || 7334,
      }),
    },
    network_refresh: {
      label: 'Re-probe all services',
      method: 'POST', path: '/api/spellcaster/network/refresh',
      body: () => ({}),
    },
    install_plan: {
      label: a => `Preview install plan (${(a.features || []).length} features)`,
      method: 'POST', path: '/api/spellcaster/install/plan',
      body: a => ({ features: a.features || [] }),
    },
    demo_gen: {
      label: a => `Generate demo: ${(a.prompt || '').slice(0, 30)}${(a.prompt || '').length > 30 ? '…' : ''}`,
      method: 'POST', path: '/api/spellcaster/demo_gen',
      body: a => ({
        prompt: a.prompt || '', negative: a.negative || '',
        model:  a.model || '', timeout: parseInt(a.timeout, 10) || 90,
      }),
    },
    feedback: {
      label: a => `Log feedback (${a.rating > 0 ? '\u{1F44D}' : a.rating < 0 ? '\u{1F44E}' : '\u2014'})`,
      method: 'POST', path: '/api/spellcaster/feedback',
      body: a => ({
        subject_type: a.subject_type || '',
        subject_id:   a.subject_id || '',
        rating:       parseInt(a.rating, 10) || 0,
        meta:         a.meta || {},
        note:         a.note || '',
      }),
    },
    cue_state:    { label: 'Show open issues', method: 'GET',
                     path: () => '/api/spellcaster/cue', body: () => ({}) },
    cue_enqueue:  { label: a => `Queue issue: ${a.issue ? a.issue.title || a.issue.id : '?'}`,
                     method: 'POST', path: '/api/spellcaster/cue/enqueue',
                     body: a => a.issue || {} },
    cue_resolve:  { label: a => `Mark resolved: ${a.id || '?'}`,
                     method: 'POST', path: '/api/spellcaster/cue/resolve',
                     body: a => ({ id: a.id || '', note: a.note || '' }) },
    cue_defer:    { label: a => `Defer: ${a.id || '?'}`,
                     method: 'POST', path: '/api/spellcaster/cue/defer',
                     body: a => ({ id: a.id || '', note: a.note || '' }) },
    cue_reseed:   { label: 'Reseed issue cue', method: 'POST',
                     path: '/api/spellcaster/cue/reseed', body: () => ({}) },
    finish: {
      label: 'Finish setup',
      method: 'POST', path: '/api/setup/finish', body: () => ({}),
    },
  };

  // ── Parser ────────────────────────────────────────────────────────────
  function parseActions(text) {
    if (typeof text !== 'string' || !text) {
      return { cleanText: '', actions: [] };
    }
    const actions = [];
    // Normalise: some models wrap the ACTION tag in a ``` fence. Strip those
    // fences when their only content is action tags; leave other fences
    // (code snippets the wizard might legitimately paste) alone.
    let working = text;
    // Parse ACTION tags
    working = working.replace(ACTION_RE, (_, payload) => {
      const raw = payload.trim();
      try {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object' && parsed.type) {
          actions.push(parsed);
        }
      } catch (_e) {
        // Malformed — drop it rather than leak JSON to the user
      }
      return '';
    });
    // Clean up orphaned code fences + trailing whitespace the removal left
    working = working
      .replace(/```\s*\n?\s*```/g, '')     // empty fenced block
      .replace(/\n{3,}/g, '\n\n')
      .trim();
    return { cleanText: working, actions };
  }

  // ── Renderer ──────────────────────────────────────────────────────────
  function renderActionButtons(parentEl, actions) {
    if (!parentEl || !Array.isArray(actions) || !actions.length) return 0;
    let rendered = 0;
    const row = document.createElement('div');
    row.className = 'sc-action-row';
    for (const action of actions) {
      const spec = ACTION_MAP[action.type];
      if (!spec) continue;
      const btn = document.createElement('button');
      btn.className = 'sc-action-btn';
      btn.dataset.actionType = action.type;
      const label = typeof spec.label === 'function' ? spec.label(action) : spec.label;
      btn.textContent = label;
      btn.addEventListener('click', () => dispatchAction(action, btn, spec, label));
      row.appendChild(btn);
      rendered += 1;
    }
    if (rendered) parentEl.appendChild(row);
    return rendered;
  }

  // ── Dispatch ──────────────────────────────────────────────────────────
  async function dispatchAction(action, btn, spec, label) {
    btn.disabled = true;
    const originalText = label;
    btn.innerHTML = `<span class="sc-action-spinner"></span>${label}`;
    const url = typeof spec.path === 'function' ? spec.path(action) : spec.path;
    const init = { method: spec.method, headers: { 'Content-Type': 'application/json' } };
    if (spec.method !== 'GET') {
      init.body = JSON.stringify(spec.body(action));
    }
    try {
      const resp = await fetch(url, init);
      const bodyText = await resp.text();
      let body;
      try { body = JSON.parse(bodyText); } catch { body = { raw: bodyText }; }
      if (resp.ok) {
        btn.classList.add('sc-action-btn-done');
        btn.textContent = '\u2713 ' + originalText;
        btn.title = JSON.stringify(body).slice(0, 500);
      } else {
        btn.classList.add('sc-action-btn-err');
        btn.textContent = '\u2717 ' + originalText;
        btn.title = body.error || body.raw || ('HTTP ' + resp.status);
      }
    } catch (e) {
      btn.classList.add('sc-action-btn-err');
      btn.textContent = '\u2717 ' + originalText;
      btn.title = e.message || 'request failed';
    }
  }

  // ── Public surface ────────────────────────────────────────────────────
  global.SpellcasterActions = {
    parseActions,
    renderActionButtons,
    dispatchAction,
    ACTION_MAP,
  };
})(window);
