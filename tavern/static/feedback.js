/* Spellcaster Feedback — universal 👍/👎 on any output.
 *
 * Exposes:
 *   window.SpellcasterFeedback.attach(containerEl, subjectType, subjectId, meta)
 *     - Inserts a small 👍/👎 row after `containerEl`.
 *     - meta fields (model, cfg, steps, sampler, scheduler, seed, prompt, ...)
 *       are sent to the backend on click so +1 can be blessed into
 *       CalibrationProfile.
 *
 *   window.SpellcasterFeedback.summary(subjectType?)
 *     - Returns { ups, downs, ratio, entries[] } for the given stream or "all".
 *
 * Designed to be called from every surface that renders a generated output:
 *   - chat images (app.js::addGenerationMessage)
 *   - LoRA shootout tiles (lora_shootout.js — secondary alongside "Pick")
 *   - scaffold calibration sample galleries (future frontend)
 *   - demo_gen renders
 *
 * Idempotent per element: re-attaching to the same container is a no-op
 * (the helper stamps data-sc-feedback="yes" on the anchor).
 */
(function () {
  'use strict';
  if (window.SpellcasterFeedback) return;  // idempotent

  // ── Styles ────────────────────────────────────────────────────────
  const STYLE_ID = 'sc-feedback-style';
  if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = `
      .sc-fb-row {
        display: inline-flex; gap: 6px; align-items: center;
        margin: 4px 0 0 0;
        user-select: none;
      }
      .sc-fb-btn {
        background: rgba(26, 23, 48, 0.6); color: #a89bcc;
        border: 1px solid rgba(106, 27, 154, 0.4); border-radius: 14px;
        font-size: 14px; padding: 3px 10px; line-height: 1.2;
        cursor: pointer; transition: transform .1s ease, background .15s ease;
      }
      .sc-fb-btn:hover { transform: translateY(-1px);
        background: rgba(106, 27, 154, 0.25); color: #e8e6f5; }
      .sc-fb-btn[data-active="up"]   {
        background: rgba(76, 175, 80, 0.25); color: #81c784;
        border-color: #4caf50; }
      .sc-fb-btn[data-active="down"] {
        background: rgba(244, 67, 54, 0.25); color: #ef5350;
        border-color: #f44336; }
      .sc-fb-btn[disabled] { opacity: 0.6; cursor: default; }
      .sc-fb-label {
        color: #8a7eaf; font-size: 11px; margin-left: 4px;
      }
    `;
    document.head.appendChild(style);
  }

  // ── POST helper ───────────────────────────────────────────────────
  async function submit(subjectType, subjectId, rating, meta, note) {
    const resp = await fetch('/api/spellcaster/feedback', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subject_type: subjectType,
        subject_id:   subjectId,
        rating:       rating,
        meta:         meta || {},
        note:         note || '',
      }),
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(text || `HTTP ${resp.status}`);
    }
    return resp.json();
  }

  async function summary(subjectType) {
    const qs = subjectType ? `?subject_type=${encodeURIComponent(subjectType)}` : '';
    const resp = await fetch(`/api/spellcaster/feedback${qs}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  }

  // ── attach() — inject 👍/👎 next to a media element ───────────────
  function attach(container, subjectType, subjectId, meta) {
    if (!container || container.getAttribute('data-sc-feedback') === 'yes') {
      return;                     // already attached
    }
    container.setAttribute('data-sc-feedback', 'yes');

    const row = document.createElement('div');
    row.className = 'sc-fb-row';

    const up = document.createElement('button');
    up.className = 'sc-fb-btn';
    up.type = 'button';
    up.innerHTML = '👍';
    up.title = 'This is good — bless these settings as my default for this model';

    const down = document.createElement('button');
    down.className = 'sc-fb-btn';
    down.type = 'button';
    down.innerHTML = '👎';
    down.title = 'This is bad — log it so I know this combo misses';

    const label = document.createElement('span');
    label.className = 'sc-fb-label';

    row.appendChild(up); row.appendChild(down); row.appendChild(label);

    async function vote(rating, btn) {
      if (btn.disabled) return;
      up.disabled = down.disabled = true;
      label.textContent = '…';
      try {
        const r = await submit(subjectType, subjectId, rating, meta);
        btn.setAttribute('data-active', rating === 1 ? 'up' : 'down');
        if (rating === 1) {
          label.textContent = r.blessed
            ? '✓ blessed as default'
            : '✓ noted';
        } else {
          label.textContent = '✓ noted';
        }
      } catch (e) {
        label.textContent = `✗ ${e.message}`;
      } finally {
        up.disabled = down.disabled = false;
      }
    }

    up.addEventListener('click',   () => vote( 1, up));
    down.addEventListener('click', () => vote(-1, down));

    // Insert after container (so the row is visually below the image).
    if (container.parentNode) {
      container.parentNode.insertBefore(row, container.nextSibling);
    } else {
      // Fallback — append to container itself.
      container.appendChild(row);
    }
  }

  window.SpellcasterFeedback = { attach, submit, summary };
})();
